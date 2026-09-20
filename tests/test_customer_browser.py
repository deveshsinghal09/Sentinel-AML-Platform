from __future__ import annotations

import duckdb

from api.repositories import customer_repository
from tools.customer_browser import get_customer, list_customers


def _database():
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE transactions (
            timestamp TIMESTAMP,
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
        "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "2022-09-18 12:00:00",
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
    connection.execute(
        """
        CREATE TABLE alert_queue (
            entity_id VARCHAR,
            risk_score DOUBLE,
            status VARCHAR
        )
        """
    )
    connection.execute(
        "INSERT INTO alert_queue VALUES ('ACC-001', 0.82, 'new')"
    )
    return connection


def _patch_table(monkeypatch):
    monkeypatch.setattr(
        customer_repository,
        "resolve_transaction_table",
        lambda connection, dataset_id=None: '"transactions"',
    )


def test_customer_browser_ranks_and_filters_current_workflow_risk(monkeypatch):
    connection = _database()
    _patch_table(monkeypatch)
    try:
        rows, total = list_customers(
            risk_label="high",
            limit=10,
            conn=connection,
        )
    finally:
        connection.close()

    assert total == 1
    assert rows[0].account_id == "ACC-001"
    assert rows[0].risk_label == "high"
    assert rows[0].alert_count == 1
    assert rows[0].open_alert_count == 1


def test_customer_detail_consolidates_activity_and_counterparties(
    monkeypatch,
):
    connection = _database()
    _patch_table(monkeypatch)
    try:
        detail = get_customer("ACC-001", conn=connection)
    finally:
        connection.close()

    assert detail is not None
    assert detail.summary.outbound_count == 1
    assert detail.summary.inbound_count == 1
    assert detail.known_laundering_transactions == 1
    assert detail.payment_formats == {"Wire": 1, "ACH": 1}
    assert detail.alerts == []
    assert {
        item.account_id for item in detail.top_counterparties
    } == {"ACC-002", "ACC-003"}


def test_customer_browser_remains_available_before_workflow_schema(monkeypatch):
    connection = _database()
    connection.execute("DROP TABLE alert_queue")
    _patch_table(monkeypatch)
    try:
        rows, total = list_customers(limit=10, conn=connection)
    finally:
        connection.close()

    assert total == 3
    assert all(item.risk_label == "unscored" for item in rows)
