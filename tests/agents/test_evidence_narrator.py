from __future__ import annotations

from agent.explanation.contracts import NarrationRequest
from agent.explanation.evidence_narrator import EvidenceNarrationAgent


def _request(**overrides):
    values = {
        "query": "Find structuring",
        "entity_id": "ACC-17",
        "risk_score": 0.86,
        "risk_label": "high",
        "escalation_action": "report",
        "typology": "structuring",
        "rule_flags": ["SUB_THRESHOLD_CLUSTER", "HIGH_VELOCITY"],
        "transaction_count": 8,
        "total_amount": 78_400,
        "observation_window": ("2026-06-04", "2026-06-07"),
        "distinct_counterparties": 6,
        "evidence": [{"transaction_id": "TX-1", "amount": 9_800}],
        "citations": ["https://www.fincen.gov/guidance"],
    }
    values.update(overrides)
    return NarrationRequest(**values)


def test_narrative_reconciles_exact_metrics_and_reviewer_action():
    narrative = EvidenceNarrationAgent().narrate(_request())

    assert "8 transactions" in narrative.explanation
    assert "$78,400.00" in narrative.explanation
    assert "2026-06-04 through 2026-06-07" in narrative.explanation
    assert "6 distinct counterparties" in narrative.explanation
    assert "senior AML reviewer" in narrative.recommendation
    assert narrative.citations == ["https://www.fincen.gov/guidance"]


def test_narrative_never_states_that_money_laundering_occurred():
    narrative = EvidenceNarrationAgent().narrate(_request())

    assert "potential structuring" in narrative.explanation
    assert "not a conclusion of illicit activity" in narrative.explanation
    assert "is money laundering" not in narrative.explanation.lower()


def test_missing_rows_and_citations_are_disclosed():
    narrative = EvidenceNarrationAgent().narrate(
        _request(evidence=[], citations=[])
    )

    assert len(narrative.limitations) == 2
    assert "No transaction-level rows" in narrative.limitations[0]
    assert "ungrounded" in narrative.limitations[1]


def test_duplicate_citations_are_removed_without_reordering():
    narrative = EvidenceNarrationAgent().narrate(
        _request(citations=["https://a.test", "https://a.test", "https://b.test"])
    )

    assert narrative.citations == ["https://a.test", "https://b.test"]
