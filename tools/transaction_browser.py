"""Model-facing transaction evidence browser over the repository layer."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import duckdb

from agent.models import TransactionRecord
from api.repositories.transaction_repository import (
    TransactionFilters,
    TransactionRepository,
)
from tools.data_loader import get_db_connection


def _iso(value: Any) -> str:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value))
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def list_transactions(
    *,
    account_id: str | None = None,
    direction: str = "both",
    payment_format: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    laundering_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    dataset_id: str | None = None,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> tuple[list[TransactionRecord], int]:
    own_connection = conn is None
    database = conn or get_db_connection()
    try:
        repository = TransactionRepository(
            database,
            dataset_id=dataset_id,
        )
        rows, total = repository.list(
            TransactionFilters(
                account_id=account_id,
                direction=direction,
                payment_format=payment_format,
                min_amount=min_amount,
                max_amount=max_amount,
                date_from=date_from,
                date_to=date_to,
                laundering_only=laundering_only,
            ),
            limit=limit,
            offset=offset,
        )
        return (
            [
                TransactionRecord(
                    transaction_id=row.transaction_id,
                    timestamp=_iso(row.timestamp),
                    from_bank=row.from_bank,
                    from_account=row.from_account,
                    to_bank=row.to_bank,
                    to_account=row.to_account,
                    amount_paid=row.amount_paid,
                    amount_received=row.amount_received,
                    paying_currency=row.paying_currency,
                    receiving_currency=row.receiving_currency,
                    payment_format=row.payment_format,
                    is_laundering=row.is_laundering,
                )
                for row in rows
            ],
            total,
        )
    finally:
        if own_connection:
            database.close()


def payment_formats(
    *,
    dataset_id: str | None = None,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> list[str]:
    own_connection = conn is None
    database = conn or get_db_connection()
    try:
        return TransactionRepository(
            database,
            dataset_id=dataset_id,
        ).payment_formats()
    finally:
        if own_connection:
            database.close()
