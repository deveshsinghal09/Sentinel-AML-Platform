from __future__ import annotations

from datetime import UTC, datetime

from agent.reporting.report_packager import ReportPackagingAgent


def _response():
    return {
        "query": "Find structuring in June",
        "intent": {
            "intent": "pattern_search",
            "pattern_type": "structuring",
            "filters": {
                "date_range": ["2026-06-01", "2026-06-30"],
                "max_amount": 10_000,
            },
        },
        "plan": {
            "steps": [
                "data_loader",
                "feature_engineering",
                "rule_engine",
                "risk_engine",
            ],
            "skipped": [
                {"tool": "eda", "reason": "Targeted query"},
                {"tool": "ml_engine", "reason": "Rules are sufficient"},
            ],
            "reasoning": "Targeted structuring analysis.",
        },
        "top_entities": [
            {
                "entity_id": "ACC-17",
                "risk_score": 0.88,
                "risk_label": "high",
                "escalation_action": "report",
                "explanation": "Eight sub-threshold transactions in four days.",
                "rule_flags": ["STRUCTURING"],
                "txn_count": 8,
                "total_amount": 78_400,
                "top_transactions": [{"txn_id": "TX-1", "amount": 9_800}],
                "citation": "https://www.fincen.gov/guidance",
                "sar_draft": "Draft narrative requiring reviewer approval.",
            },
            {
                "entity_id": "ACC-18",
                "risk_score": 0.55,
                "risk_label": "medium",
                "escalation_action": "flag_for_review",
                "explanation": "Elevated velocity.",
                "rule_flags": ["VELOCITY"],
                "txn_count": 4,
                "total_amount": 12_000,
                "top_transactions": [],
                "citation": "",
                "sar_draft": "Must not package a medium-risk SAR draft.",
            },
        ],
    }


def test_package_preserves_plan_findings_citations_and_approval_state():
    package = ReportPackagingAgent().package(
        "inv-001",
        _response(),
        generated_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
    )

    assert package.selected_tools == [
        "data_loader",
        "feature_engineering",
        "rule_engine",
        "risk_engine",
    ]
    assert package.skipped_tools[0]["tool"] == "eda"
    assert [finding.entity_id for finding in package.findings] == [
        "ACC-17",
        "ACC-18",
    ]
    assert package.citations == ["https://www.fincen.gov/guidance"]
    assert [draft.entity_id for draft in package.sar_drafts] == ["ACC-17"]
    assert package.sar_drafts[0].status == "draft_requires_authorized_review"
    assert "not a determination" in package.disclaimer


def test_package_discloses_missing_evidence_and_grounding():
    package = ReportPackagingAgent().package("inv-001", _response())

    assert any("ACC-18: no transaction-level" in item for item in package.warnings)
    assert any("ACC-18: no AML knowledge citation" in item for item in package.warnings)


def test_checksum_is_stable_for_equivalent_response_ordering():
    response = _response()
    reversed_response = dict(reversed(list(response.items())))

    first = ReportPackagingAgent().package("inv-001", response)
    second = ReportPackagingAgent().package("inv-001", reversed_response)

    assert first.evidence_checksum == second.evidence_checksum
    assert len(first.evidence_checksum) == 64


def test_packager_does_not_author_a_missing_sar_draft():
    response = _response()
    response["top_entities"][0]["sar_draft"] = ""

    package = ReportPackagingAgent().package("inv-001", response)

    assert package.sar_drafts == []
