from __future__ import annotations

from datetime import datetime

import duckdb
from fastapi.testclient import TestClient

import tools.workflow_store as workflow_store
from api.main import app
from tools.customer_browser import get_customer, list_customers
from tools.transaction_browser import list_transactions, payment_formats
from tools.workflow_store import initialize_workflow_schema


def evidence_connection():
    conn = duckdb.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE transactions (
            timestamp TIMESTAMP,
            from_bank VARCHAR,
            from_account VARCHAR,
            to_bank VARCHAR,
            to_account VARCHAR,
            amount_received DOUBLE,
            receiving_currency VARCHAR,
            amount_paid DOUBLE,
            paying_currency VARCHAR,
            payment_format VARCHAR,
            is_laundering INTEGER,
            txn_date DATE,
            amount_usd DOUBLE
        )
        """
    )
    conn.executemany(
        "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                datetime(2022, 9, 1, 9, 0), "001", "A", "002", "B",
                9_000.0, "USD", 9_000.0, "USD", "Wire", 1,
                "2022-09-01", 9_000.0,
            ),
            (
                datetime(2022, 9, 2, 10, 0), "001", "A", "003", "C",
                500.0, "USD", 500.0, "USD", "ACH", 0,
                "2022-09-02", 500.0,
            ),
            (
                datetime(2022, 9, 3, 11, 0), "004", "D", "001", "A",
                1_200.0, "USD", 1_200.0, "USD", "Cheque", 0,
                "2022-09-03", 1_200.0,
            ),
            (
                datetime(2022, 9, 4, 12, 0), "001", "A", "001", "A",
                250.0, "USD", 250.0, "USD", "Cash", 0,
                "2022-09-04", 250.0,
            ),
        ],
    )
    initialize_workflow_schema(conn)
    conn.execute(
        """
        INSERT INTO alert_queue (
            alert_id, entity_id, investigation_id, risk_score, risk_label,
            escalation_action, saml_d_typology, created_at, sla_hours,
            assigned_to, status, disposition, notes
        ) VALUES (
            'ALT-A', 'A', 'INV-A', 0.82, 'high', 'flag_for_review',
            'Structuring', now(), 24, NULL, 'new', 'pending', ''
        )
        """
    )
    return conn


def test_customer_list_combines_inbound_outbound_and_workflow_risk():
    conn = evidence_connection()
    items, total = list_customers(limit=10, conn=conn)
    customer = next(item for item in items if item.account_id == "A")
    assert total == 4
    assert customer.outbound_count == 3
    assert customer.inbound_count == 2
    assert customer.distinct_counterparties == 3
    assert customer.risk_label == "high"
    assert customer.open_alert_count == 1


def test_customer_detail_returns_relationships_mix_and_alerts():
    conn = evidence_connection()
    detail = get_customer("A", conn=conn)
    assert detail is not None
    assert detail.payment_formats == {"Wire": 1, "ACH": 1, "Cheque": 1, "Cash": 1}
    assert detail.known_laundering_transactions == 1
    assert {item.account_id for item in detail.top_counterparties} == {"B", "C", "D"}
    assert detail.alerts[0].alert_id == "ALT-A"
    assert get_customer("MISSING", conn=conn) is None


def test_customer_reads_do_not_repeat_workflow_schema_writes(monkeypatch):
    conn = evidence_connection()

    def unexpected_schema_write(_conn):
        raise AssertionError("read path attempted workflow schema DDL")

    monkeypatch.setattr(
        workflow_store,
        "initialize_workflow_schema",
        unexpected_schema_write,
    )
    items, total = list_customers(search="A", conn=conn)
    assert total == 1
    assert items[0].account_id == "A"
    assert get_customer("A", conn=conn) is not None


def test_transaction_browser_filters_direction_amount_and_source_label():
    conn = evidence_connection()
    outbound, total = list_transactions(
        account_id="A",
        direction="outbound",
        min_amount=1_000,
        laundering_only=True,
        conn=conn,
    )
    assert total == 1
    assert outbound[0].from_account == "A"
    assert outbound[0].is_laundering
    assert outbound[0].transaction_id.startswith("TXN-")
    assert payment_formats(conn=conn) == ["ACH", "Cash", "Cheque", "Wire"]
    linked, linked_total = list_transactions(account_id="A", conn=conn)
    assert linked_total == 4
    assert len(linked) == 4


def test_evidence_api_rejects_unsafe_filter_combinations():
    with TestClient(app) as client:
        assert client.get("/transactions?direction=inbound").status_code == 422
        assert client.get("/transactions?min_amount=10&max_amount=5").status_code == 422
        assert client.get("/transactions?date_from=2022-09-02&date_to=2022-09-01").status_code == 422
        assert client.get("/customers?risk_label=critical").status_code == 422
