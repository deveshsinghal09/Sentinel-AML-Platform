"""Parameterized transaction evidence access over a governed dataset table."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

import duckdb

from tools.dataset_store import resolve_transaction_table


Direction = Literal["both", "inbound", "outbound"]


@dataclass(frozen=True, slots=True)
class TransactionFilters:
    account_id: str | None = None
    direction: Direction = "both"
    payment_format: str | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    date_from: date | None = None
    date_to: date | None = None
    laundering_only: bool = False

    def __post_init__(self) -> None:
        if self.direction not in {"both", "inbound", "outbound"}:
            raise ValueError("Unsupported transaction direction")
        if self.direction != "both" and not self.account_id:
            raise ValueError("Direction requires an account_id")
        if self.min_amount is not None and self.min_amount < 0:
            raise ValueError("min_amount cannot be negative")
        if self.max_amount is not None and self.max_amount < 0:
            raise ValueError("max_amount cannot be negative")
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("min_amount cannot exceed max_amount")
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from cannot be after date_to")


@dataclass(frozen=True, slots=True)
class TransactionRow:
    transaction_id: str
    timestamp: datetime
    from_bank: str
    from_account: str
    to_bank: str
    to_account: str
    amount_paid: float
    amount_received: float
    paying_currency: str
    receiving_currency: str
    payment_format: str
    is_laundering: bool


class TransactionRepository:
    """Read-only transaction repository bound to one DuckDB connection."""

    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        dataset_id: str | None = None,
    ):
        self._connection = connection
        self._table = resolve_transaction_table(connection, dataset_id)

    @staticmethod
    def _where(filters: TransactionFilters) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if filters.account_id:
            if filters.direction == "outbound":
                clauses.append("from_account = ?")
                parameters.append(filters.account_id)
            elif filters.direction == "inbound":
                clauses.append("to_account = ?")
                parameters.append(filters.account_id)
            else:
                clauses.append("(from_account = ? OR to_account = ?)")
                parameters.extend([filters.account_id, filters.account_id])
        if filters.payment_format:
            clauses.append("lower(payment_format) = lower(?)")
            parameters.append(filters.payment_format)
        if filters.min_amount is not None:
            clauses.append("amount_paid >= ?")
            parameters.append(filters.min_amount)
        if filters.max_amount is not None:
            clauses.append("amount_paid <= ?")
            parameters.append(filters.max_amount)
        if filters.date_from is not None:
            clauses.append("txn_date >= ?")
            parameters.append(filters.date_from)
        if filters.date_to is not None:
            clauses.append("txn_date <= ?")
            parameters.append(filters.date_to)
        if filters.laundering_only:
            clauses.append("is_laundering = 1")
        return (
            "WHERE " + " AND ".join(clauses) if clauses else "",
            parameters,
        )

    def list(
        self,
        filters: TransactionFilters,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TransactionRow], int]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if offset < 0:
            raise ValueError("offset cannot be negative")
        where, parameters = self._where(filters)
        total = int(
            self._connection.execute(
                f"SELECT count(*) FROM {self._table} {where}",
                parameters,
            ).fetchone()[0]
        )
        rows = self._connection.execute(
            f"""
            SELECT
                'TXN-' || upper(substr(md5(
                    concat_ws('|', cast(timestamp AS VARCHAR), from_bank,
                              from_account, to_bank, to_account,
                              cast(amount_paid AS VARCHAR), payment_format)
                ), 1, 12)) AS transaction_id,
                timestamp, from_bank, from_account, to_bank, to_account,
                amount_paid, amount_received, paying_currency,
                receiving_currency, payment_format, is_laundering
            FROM {self._table}
            {where}
            ORDER BY timestamp DESC, transaction_id
            LIMIT ? OFFSET ?
            """,
            [*parameters, limit, offset],
        ).fetchall()
        return (
            [
                TransactionRow(
                    transaction_id=row[0],
                    timestamp=row[1],
                    from_bank=row[2] or "",
                    from_account=row[3] or "",
                    to_bank=row[4] or "",
                    to_account=row[5] or "",
                    amount_paid=float(row[6] or 0),
                    amount_received=float(row[7] or 0),
                    paying_currency=row[8] or "",
                    receiving_currency=row[9] or "",
                    payment_format=row[10] or "",
                    is_laundering=bool(row[11]),
                )
                for row in rows
            ],
            total,
        )

    def payment_formats(self) -> list[str]:
        return [
            row[0]
            for row in self._connection.execute(
                f"""
                SELECT DISTINCT payment_format
                FROM {self._table}
                WHERE payment_format IS NOT NULL
                  AND trim(payment_format) <> ''
                ORDER BY lower(payment_format), payment_format
                """
            ).fetchall()
        ]
