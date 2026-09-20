from __future__ import annotations

import pytest

from agent.models import CustomerSummary
from api.services.evidence_service import (
    EvidenceNotFound,
    EvidenceService,
    EvidenceUnavailable,
)


class Backend:
    def list_customers(self, **filters):
        return [], 0

    def get_customer(self, account_id):
        return None

    def list_transactions(self, **filters):
        return [], 0

    def payment_formats(self):
        return [" wire ", "WIRE", "ACH", ""]


def test_service_normalizes_payment_formats_case_insensitively():
    service = EvidenceService(Backend())

    assert service.payment_formats() == ["ACH", "wire"]


def test_service_distinguishes_missing_evidence_from_backend_failure():
    service = EvidenceService(Backend())

    with pytest.raises(EvidenceNotFound):
        service.get_customer("ACC-404")

    class FailingBackend(Backend):
        def get_customer(self, account_id):
            raise RuntimeError("private database location")

    with pytest.raises(EvidenceUnavailable) as captured:
        EvidenceService(FailingBackend()).get_customer("ACC-001")
    assert "private database" not in str(captured.value)


def test_service_rejects_inconsistent_page_totals():
    customer = CustomerSummary(
        account_id="ACC-001",
        primary_bank="Bank A",
        outbound_count=1,
        inbound_count=0,
        total_sent=100,
        total_received=0,
        max_transaction=100,
        distinct_counterparties=1,
        first_seen="2022-09-01T00:00:00Z",
        last_seen="2022-09-01T00:00:00Z",
        alert_count=0,
        open_alert_count=0,
        max_risk_score=None,
        risk_label="unscored",
    )

    class InconsistentBackend(Backend):
        def list_customers(self, **filters):
            return [customer], 0

    with pytest.raises(EvidenceUnavailable):
        EvidenceService(InconsistentBackend()).list_customers(
            search=None,
            risk_label=None,
            limit=50,
            offset=0,
        )
