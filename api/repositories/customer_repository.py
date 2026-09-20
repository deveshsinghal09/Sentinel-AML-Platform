"""Customer activity repository with optional workflow-risk enrichment."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import duckdb

from tools.dataset_store import resolve_transaction_table


RiskFilter = Literal["unscored", "low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class CustomerRow:
    account_id: str
    primary_bank: str
    outbound_count: int
    inbound_count: int
    total_sent: float
    total_received: float
    max_transaction: float
    distinct_counterparties: int
    first_seen: datetime
    last_seen: datetime
    alert_count: int
    open_alert_count: int
    max_risk_score: float | None


@dataclass(frozen=True, slots=True)
class CounterpartyRow:
    account_id: str
    transaction_count: int
    total_amount: float
    direction: Literal["inbound", "outbound"]


@dataclass(frozen=True, slots=True)
class CustomerProfile:
    summary: CustomerRow
    payment_formats: dict[str, int]
    currencies: list[str]
    known_laundering_transactions: int
    top_counterparties: list[CounterpartyRow]


_CUSTOMER_QUERY = """
WITH activity AS (
    SELECT from_account AS account_id, from_bank AS bank, timestamp,
           amount_paid AS amount, to_account AS counterparty,
           1 AS outbound, 0 AS inbound
    FROM {table}
    WHERE from_account IS NOT NULL {outbound_filter}
    UNION ALL
    SELECT to_account AS account_id, to_bank AS bank, timestamp,
           amount_received AS amount, from_account AS counterparty,
           0 AS outbound, 1 AS inbound
    FROM {table}
    WHERE to_account IS NOT NULL {inbound_filter}
),
customer_activity AS (
    SELECT account_id, min(bank) AS primary_bank,
           sum(outbound)::BIGINT AS outbound_count,
           sum(inbound)::BIGINT AS inbound_count,
           coalesce(sum(amount) FILTER (WHERE outbound = 1), 0) AS total_sent,
           coalesce(sum(amount) FILTER (WHERE inbound = 1), 0) AS total_received,
           max(amount) AS max_transaction,
           count(DISTINCT counterparty)
               FILTER (WHERE counterparty <> account_id)
               AS distinct_counterparties,
           min(timestamp) AS first_seen, max(timestamp) AS last_seen
    FROM activity
    GROUP BY account_id
),
{alerts_cte}
SELECT c.account_id, c.primary_bank, c.outbound_count, c.inbound_count,
       c.total_sent, c.total_received, c.max_transaction,
       c.distinct_counterparties, c.first_seen, c.last_seen,
       coalesce(a.alert_count, 0), a.max_risk,
       coalesce(a.open_alert_count, 0)
FROM customer_activity c
LEFT JOIN alerts a ON a.entity_id = c.account_id
"""


class CustomerRepository:
    """Read-only customer aggregation over one governed evidence workspace."""

    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        dataset_id: str | None = None,
        low_threshold: float = 0.35,
        high_threshold: float = 0.70,
    ):
        if not 0 <= low_threshold < high_threshold <= 1:
            raise ValueError("Risk thresholds must be ordered within [0, 1]")
        self._connection = connection
        self._table = resolve_transaction_table(connection, dataset_id)
        self._low_threshold = low_threshold
        self._high_threshold = high_threshold

    def _alerts_cte(self) -> str:
        exists = bool(
            self._connection.execute(
                """
                SELECT count(*) FROM information_schema.tables
                WHERE table_name = 'alert_queue'
                """
            ).fetchone()[0]
        )
        if not exists:
            return """
            alerts AS (
                SELECT CAST(NULL AS VARCHAR) AS entity_id,
                       CAST(0 AS BIGINT) AS alert_count,
                       CAST(NULL AS DOUBLE) AS max_risk,
                       CAST(0 AS BIGINT) AS open_alert_count
                WHERE false
            )
            """
        return """
        alerts AS (
            SELECT entity_id, count(*) AS alert_count,
                   max(risk_score) AS max_risk,
                   count(*) FILTER (WHERE status <> 'closed')
                       AS open_alert_count
            FROM alert_queue
            GROUP BY entity_id
        )
        """

    def _query(
        self,
        *,
        outbound_filter: str = "",
        inbound_filter: str = "",
    ) -> str:
        return _CUSTOMER_QUERY.format(
            table=self._table,
            outbound_filter=outbound_filter,
            inbound_filter=inbound_filter,
            alerts_cte=self._alerts_cte(),
        )

    @staticmethod
    def _row(value: tuple[Any, ...]) -> CustomerRow:
        return CustomerRow(
            account_id=value[0],
            primary_bank=value[1] or "",
            outbound_count=int(value[2]),
            inbound_count=int(value[3]),
            total_sent=float(value[4] or 0),
            total_received=float(value[5] or 0),
            max_transaction=float(value[6] or 0),
            distinct_counterparties=int(value[7]),
            first_seen=value[8],
            last_seen=value[9],
            alert_count=int(value[10]),
            max_risk_score=(
                float(value[11]) if value[11] is not None else None
            ),
            open_alert_count=int(value[12]),
        )

    def _risk_clause(self, risk_filter: RiskFilter | None) -> str:
        if risk_filter is None:
            return ""
        if risk_filter == "unscored":
            return " WHERE max_risk IS NULL"
        if risk_filter == "high":
            return " WHERE max_risk >= ?"
        if risk_filter == "medium":
            return " WHERE max_risk >= ? AND max_risk < ?"
        if risk_filter == "low":
            return " WHERE max_risk < ?"
        raise ValueError("Unsupported risk label")

    def _risk_parameters(
        self,
        risk_filter: RiskFilter | None,
    ) -> list[float]:
        if risk_filter == "high":
            return [self._high_threshold]
        if risk_filter == "medium":
            return [self._low_threshold, self._high_threshold]
        if risk_filter == "low":
            return [self._low_threshold]
        return []

    def list(
        self,
        *,
        search: str | None = None,
        risk_filter: RiskFilter | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CustomerRow], int]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if offset < 0:
            raise ValueError("offset cannot be negative")
        term = search.strip() if search else None
        pattern = f"%{term}%" if term else None
        query = self._query(
            outbound_filter="AND from_account ILIKE ?" if pattern else "",
            inbound_filter="AND to_account ILIKE ?" if pattern else "",
        )
        search_parameters: list[Any] = (
            [pattern, pattern] if pattern else []
        )
        risk_clause = self._risk_clause(risk_filter)
        parameters = [
            *search_parameters,
            *self._risk_parameters(risk_filter),
        ]
        rows = self._connection.execute(
            f"""
            SELECT customers.*, count(*) OVER () AS filtered_total
            FROM ({query}{risk_clause}) customers
            ORDER BY max_risk DESC NULLS LAST,
                     (outbound_count + inbound_count) DESC,
                     account_id
            LIMIT ? OFFSET ?
            """,
            [*parameters, limit, offset],
        ).fetchall()
        total = int(rows[0][13]) if rows else 0
        if not rows and offset:
            total = int(
                self._connection.execute(
                    f"SELECT count(*) FROM ({query}{risk_clause}) customers",
                    parameters,
                ).fetchone()[0]
            )
        return [self._row(row) for row in rows], total

    def get(self, account_id: str) -> CustomerProfile | None:
        query = self._query(
            outbound_filter="AND from_account = ?",
            inbound_filter="AND to_account = ?",
        )
        row = self._connection.execute(
            query,
            [account_id, account_id],
        ).fetchone()
        if row is None:
            return None
        payment_formats = {
            item[0] or "Unknown": int(item[1])
            for item in self._connection.execute(
                f"""
                SELECT payment_format, count(*)
                FROM {self._table}
                WHERE from_account = ? OR to_account = ?
                GROUP BY payment_format
                ORDER BY count(*) DESC, payment_format
                """,
                [account_id, account_id],
            ).fetchall()
        }
        currencies = [
            item[0]
            for item in self._connection.execute(
                f"""
                SELECT DISTINCT currency
                FROM (
                    SELECT paying_currency AS currency FROM {self._table}
                    WHERE from_account = ?
                    UNION
                    SELECT receiving_currency AS currency FROM {self._table}
                    WHERE to_account = ?
                )
                WHERE currency IS NOT NULL AND currency <> ''
                ORDER BY currency
                """,
                [account_id, account_id],
            ).fetchall()
        ]
        laundering_count = int(
            self._connection.execute(
                f"""
                SELECT count(*) FROM {self._table}
                WHERE (from_account = ? OR to_account = ?)
                  AND is_laundering = 1
                """,
                [account_id, account_id],
            ).fetchone()[0]
        )
        counterparties = [
            CounterpartyRow(
                account_id=item[0],
                transaction_count=int(item[1]),
                total_amount=float(item[2] or 0),
                direction=item[3],
            )
            for item in self._connection.execute(
                f"""
                SELECT counterparty, count(*) AS transaction_count,
                       sum(amount) AS total_amount, direction
                FROM (
                    SELECT to_account AS counterparty,
                           amount_paid AS amount, 'outbound' AS direction
                    FROM {self._table}
                    WHERE from_account = ? AND to_account <> ?
                    UNION ALL
                    SELECT from_account AS counterparty,
                           amount_received AS amount, 'inbound' AS direction
                    FROM {self._table}
                    WHERE to_account = ? AND from_account <> ?
                )
                GROUP BY counterparty, direction
                ORDER BY total_amount DESC, counterparty
                LIMIT 12
                """,
                [account_id, account_id, account_id, account_id],
            ).fetchall()
        ]
        return CustomerProfile(
            summary=self._row(row),
            payment_formats=payment_formats,
            currencies=currencies,
            known_laundering_transactions=laundering_count,
            top_counterparties=counterparties,
        )
