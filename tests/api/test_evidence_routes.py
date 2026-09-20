from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.models import (
    CustomerDetail,
    CustomerSummary,
    TransactionRecord,
)
from api.routes import evidence
from api.services.auth_service import AuthSession, AuthUser
from api.services.evidence_service import EvidenceService


SESSION = AuthSession(
    user=AuthUser(
        user_id="usr-auditor-1",
        email="auditor@institution.test",
        display_name="Avery Auditor",
        roles=["auditor"],
    ),
    expires_at="2026-07-27T10:00:00Z",
)

CUSTOMER = CustomerSummary(
    account_id="ACC-001",
    primary_bank="Bank A",
    outbound_count=8,
    inbound_count=3,
    total_sent=72_000,
    total_received=25_000,
    max_transaction=9_500,
    distinct_counterparties=6,
    first_seen="2022-09-01T10:00:00Z",
    last_seen="2022-09-18T12:00:00Z",
    alert_count=2,
    open_alert_count=1,
    max_risk_score=0.82,
    risk_label="high",
)

TRANSACTION = TransactionRecord(
    transaction_id="TXN-001",
    timestamp="2022-09-18T12:00:00Z",
    from_bank="Bank A",
    from_account="ACC-001",
    to_bank="Bank B",
    to_account="ACC-002",
    amount_paid=9_500,
    amount_received=9_500,
    paying_currency="USD",
    receiving_currency="USD",
    payment_format="Wire",
    is_laundering=False,
)


class FakeEvidenceRepository:
    def __init__(self):
        self.customer_filters = None
        self.transaction_filters = None

    def list_customers(self, **filters):
        self.customer_filters = filters
        return [deepcopy(CUSTOMER)], 1

    def get_customer(self, account_id):
        if account_id != CUSTOMER.account_id:
            return None
        return CustomerDetail(summary=deepcopy(CUSTOMER))

    def list_transactions(self, **filters):
        self.transaction_filters = filters
        return [deepcopy(TRANSACTION)], 1

    def payment_formats(self):
        return ["Wire", "ACH", "wire", ""]


def _client(repository):
    app = FastAPI()
    app.include_router(evidence.router)
    app.dependency_overrides[evidence.get_evidence_service] = (
        lambda: EvidenceService(repository)
    )
    app.dependency_overrides[evidence.require_authenticated_session] = (
        lambda: SESSION
    )
    return TestClient(app)


def test_customer_page_forwards_bounded_filters_and_returns_risk_context():
    repository = FakeEvidenceRepository()
    with _client(repository) as client:
        response = client.get(
            "/customers",
            params={
                "search": " ACC ",
                "risk_label": "high",
                "limit": 25,
                "offset": 0,
            },
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert repository.customer_filters == {
        "search": "ACC",
        "risk_label": "high",
        "limit": 25,
        "offset": 0,
    }
    assert response.json()["items"][0]["risk_label"] == "high"
    assert response.json()["total"] == 1


def test_customer_detail_is_exact_and_missing_customer_returns_404():
    with _client(FakeEvidenceRepository()) as client:
        detail = client.get("/customers/ACC-001")
        missing = client.get("/customers/ACC-404")
        invalid = client.get("/customers/not%2Fsafe")

    assert detail.status_code == 200
    assert detail.json()["summary"]["account_id"] == "ACC-001"
    assert missing.status_code == 404
    assert invalid.status_code in {404, 422}


def test_transaction_filters_are_validated_and_forwarded():
    repository = FakeEvidenceRepository()
    with _client(repository) as client:
        response = client.get(
            "/transactions",
            params={
                "account_id": "ACC-001",
                "direction": "outbound",
                "payment_format": " Wire ",
                "min_amount": 8_000,
                "max_amount": 10_000,
                "date_from": "2022-09-01",
                "date_to": "2022-09-30",
                "limit": 10,
            },
        )

    assert response.status_code == 200
    assert repository.transaction_filters["account_id"] == "ACC-001"
    assert repository.transaction_filters["direction"] == "outbound"
    assert repository.transaction_filters["payment_format"] == "Wire"
    assert repository.transaction_filters["min_amount"] == 8_000
    assert response.json()["items"][0]["transaction_id"] == "TXN-001"


def test_transaction_query_rejects_ambiguous_or_inverted_filters():
    with _client(FakeEvidenceRepository()) as client:
        missing_account = client.get(
            "/transactions?direction=inbound"
        )
        amount_range = client.get(
            "/transactions?min_amount=100&max_amount=10"
        )
        date_range = client.get(
            "/transactions?date_from=2022-10-01&date_to=2022-09-01"
        )

    assert missing_account.status_code == 422
    assert amount_range.status_code == 422
    assert date_range.status_code == 422


def test_payment_formats_are_deduplicated_and_sorted():
    with _client(FakeEvidenceRepository()) as client:
        response = client.get("/transactions/payment-formats")

    assert response.status_code == 200
    assert response.json() == {"items": ["ACH", "Wire"]}


def test_repository_errors_do_not_expose_database_details():
    class FailingRepository(FakeEvidenceRepository):
        def list_customers(self, **filters):
            raise RuntimeError("D:/bank/private/evidence.duckdb")

    with _client(FailingRepository()) as client:
        response = client.get("/customers")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Evidence is temporarily unavailable."
    }
    assert "evidence.duckdb" not in response.text
