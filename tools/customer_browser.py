"""Model-facing customer intelligence over governed repository records."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import duckdb

from agent.models import (
    CounterpartySummary,
    CustomerDetail,
    CustomerSummary,
)
from api.repositories.customer_repository import (
    CustomerRepository,
    CustomerRow,
)
from config import RISK_HIGH_THRESHOLD, RISK_LOW_THRESHOLD
from tools.data_loader import get_db_connection
from tools.workflow_store import list_entity_alerts


def _iso(value: Any) -> str:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value))
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def _summary(row: CustomerRow) -> CustomerSummary:
    risk = row.max_risk_score
    if risk is None:
        label = "unscored"
    elif risk >= RISK_HIGH_THRESHOLD:
        label = "high"
    elif risk >= RISK_LOW_THRESHOLD:
        label = "medium"
    else:
        label = "low"
    return CustomerSummary(
        account_id=row.account_id,
        primary_bank=row.primary_bank,
        outbound_count=row.outbound_count,
        inbound_count=row.inbound_count,
        total_sent=row.total_sent,
        total_received=row.total_received,
        max_transaction=row.max_transaction,
        distinct_counterparties=row.distinct_counterparties,
        first_seen=_iso(row.first_seen),
        last_seen=_iso(row.last_seen),
        alert_count=row.alert_count,
        open_alert_count=row.open_alert_count,
        max_risk_score=risk,
        risk_label=label,
    )


def _repository(
    connection: duckdb.DuckDBPyConnection,
    dataset_id: str | None,
) -> CustomerRepository:
    return CustomerRepository(
        connection,
        dataset_id=dataset_id,
        low_threshold=RISK_LOW_THRESHOLD,
        high_threshold=RISK_HIGH_THRESHOLD,
    )


def _entity_alerts(
    connection: duckdb.DuckDBPyConnection,
    account_id: str,
):
    required = {
        "alert_id",
        "entity_id",
        "investigation_id",
        "risk_score",
        "risk_label",
        "escalation_action",
        "saml_d_typology",
        "created_at",
        "sla_hours",
        "assigned_to",
        "status",
        "disposition",
        "notes",
    }
    columns = {
        row[0]
        for row in connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = 'alert_queue'
            """
        ).fetchall()
    }
    if not required.issubset(columns):
        return []
    return list_entity_alerts(account_id, conn=connection)


def list_customers(
    *,
    search: str | None = None,
    risk_label: str | None = None,
    limit: int = 50,
    offset: int = 0,
    dataset_id: str | None = None,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> tuple[list[CustomerSummary], int]:
    own_connection = conn is None
    database = conn or get_db_connection()
    try:
        rows, total = _repository(database, dataset_id).list(
            search=search,
            risk_filter=risk_label,
            limit=limit,
            offset=offset,
        )
        return [_summary(row) for row in rows], total
    finally:
        if own_connection:
            database.close()


def get_customer(
    account_id: str,
    *,
    dataset_id: str | None = None,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> CustomerDetail | None:
    own_connection = conn is None
    database = conn or get_db_connection()
    try:
        profile = _repository(database, dataset_id).get(account_id)
        if profile is None:
            return None
        return CustomerDetail(
            summary=_summary(profile.summary),
            payment_formats=profile.payment_formats,
            currencies=profile.currencies,
            known_laundering_transactions=(
                profile.known_laundering_transactions
            ),
            top_counterparties=[
                CounterpartySummary(
                    account_id=row.account_id,
                    transaction_count=row.transaction_count,
                    total_amount=row.total_amount,
                    direction=row.direction,
                )
                for row in profile.top_counterparties
            ],
            alerts=_entity_alerts(database, account_id),
        )
    finally:
        if own_connection:
            database.close()
