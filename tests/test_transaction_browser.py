from __future__ import annotations

from datetime import date

import duckdb

from api.repositories import transaction_repository
from tools.transaction_browser import list_transactions, payment_formats


def _database():
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE transactions (
            timestamp TIMESTAMP,
            txn_date DATE,
            from_bank VARCHAR,
            from_account VARCHAR,
            to_bank VARCHAR,
            to_account VARCHAR,
            amount_paid DOUBLE,
            amount_received DOUBLE,
            paying_currency VARCHAR,
            receiving_currency VARCHAR,
            payment_format VARCHAR,
            is_laundering INTEGER
        )
        """
    )
    connection.executemany(
        "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "2022-09-18 12:00:00",
                "2022-09-18",
                "Bank A",
                "ACC-001",
                "Bank B",
                "ACC-002",
                9_500,
                9_500,
                "USD",
                "USD",
                "Wire",
                1,
            ),
            (
                "2022-09-17 12:00:00",
                "2022-09-17",
                "Bank C",
                "ACC-003",
                "Bank A",
                "ACC-001",
                2_000,
                2_000,
                "USD",
                "USD",
                "ACH",
                0,
            ),
        ],
    )
    return connection


def test_transaction_browser_applies_direction_amount_and_date_filters(
    monkeypatch,
):
    connection = _database()
    monkeypatch.setattr(
        transaction_repository,
        "resolve_transaction_table",
        lambda connection, dataset_id=None: '"transactions"',
    )
    try:
        rows, total = list_transactions(
            account_id="ACC-001",
            direction="outbound",
            min_amount=9_000,
            date_from=date(2022, 9, 1),
            date_to=date(2022, 9, 30),
            limit=10,
            conn=connection,
        )
    finally:
        connection.close()

    assert total == 1
    assert rows[0].from_account == "ACC-001"
    assert rows[0].amount_paid == 9_500
    assert rows[0].transaction_id.startswith("TXN-")
    assert rows[0].timestamp.endswith("Z")


def test_transaction_browser_returns_stable_pagination_and_formats(monkeypatch):
    connection = _database()
    monkeypatch.setattr(
        transaction_repository,
        "resolve_transaction_table",
        lambda connection, dataset_id=None: '"transactions"',
    )
    try:
        first, total = list_transactions(limit=1, offset=0, conn=connection)
        second, _ = list_transactions(limit=1, offset=1, conn=connection)
        formats = payment_formats(conn=connection)
    finally:
        connection.close()

    assert total == 2
    assert first[0].transaction_id != second[0].transaction_id
    assert formats == ["ACH", "Wire"]


def test_transaction_filters_are_parameterized(monkeypatch):
    connection = _database()
    monkeypatch.setattr(
        transaction_repository,
        "resolve_transaction_table",
        lambda connection, dataset_id=None: '"transactions"',
    )
    try:
        rows, total = list_transactions(
            account_id="ACC-001' OR 1=1 --",
            conn=connection,
        )
        remaining = connection.execute(
            "SELECT count(*) FROM transactions"
        ).fetchone()[0]
    finally:
        connection.close()

    assert rows == []
    assert total == 0
    assert remaining == 2
