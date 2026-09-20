from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from agent.models import (
    AgentResponse,
    FlaggedEntity,
    IntentResult,
    PlanResult,
    SummaryStats,
)
from api.main import app
from tools.workflow_store import persist_investigation


def _response() -> AgentResponse:
    return AgentResponse(
        query="Which customers need review?",
        intent=IntentResult(intent="pattern_search", pattern_type="structuring"),
        plan=PlanResult(steps=["data_loader", "rule_engine"], reasoning="Targeted rules."),
        execution_trace=[],
        top_entities=[
            FlaggedEntity(
                entity_id="CUST-API",
                risk_score=0.82,
                risk_label="high",
                escalation_action="flag_for_review",
            )
        ],
        summary_stats=SummaryStats(total_analyzed=10, flagged=1, high_risk=1),
    )


def test_workflow_endpoints_and_audit_read_only(tmp_path, monkeypatch):
    database_path = tmp_path / "phase_b.duckdb"

    def connection():
        return duckdb.connect(str(database_path))

    monkeypatch.setattr("tools.workflow_store.get_db_connection", connection)
    seeded = persist_investigation(_response())

    with TestClient(app) as client:
        investigations = client.get("/investigations")
        assert investigations.status_code == 200
        assert investigations.json()[0]["investigation_id"] == seeded.investigation_id

        detail = client.get(f"/investigations/{seeded.investigation_id}")
        assert detail.status_code == 200
        assert detail.json()["alert_count"] == 1

        queue = client.get("/queue")
        assert queue.status_code == 200
        alert = queue.json()["items"][0]
        alert_id = alert["alert_id"]

        assignment = client.post(
            f"/queue/{alert_id}/assign",
            json={"assigned_to": "analyst.api", "actor": "supervisor.api"},
        )
        assert assignment.status_code == 200
        assert assignment.json()["status"] == "in_review"

        note = client.post(
            f"/queue/{alert_id}/notes",
            json={"note": "Reviewed payment evidence.", "actor": "analyst.api"},
        )
        assert note.status_code == 200
        assert "Reviewed payment evidence." in note.json()["notes"]

        disposition = client.post(
            f"/queue/{alert_id}/disposition",
            json={"disposition": "escalated", "actor": "analyst.api"},
        )
        assert disposition.status_code == 200
        assert disposition.json()["status"] == "escalated"

        audit = client.get("/audit")
        assert audit.status_code == 200
        assert audit.json()["total"] >= 7
        assert client.post("/audit", json={}).status_code == 405

        prohibited_filing = client.post(
            f"/queue/{alert_id}/disposition",
            json={"disposition": "sar_filed", "actor": "analyst.api"},
        )
        assert prohibited_filing.status_code == 422


@pytest.mark.requires_data
def test_governance_endpoints_expose_effective_read_only_state():
    with TestClient(app) as client:
        policy = client.get("/policy")
        assert policy.status_code == 200
        assert policy.json()["mode"] == "read_only"
        assert policy.json()["thresholds"]["structuring_upper"] == 10_000
        assert client.post("/policy", json={}).status_code == 405

        datasets = client.get("/datasets")
        assert datasets.status_code == 200
        payload = datasets.json()
        assert any(
            item["dataset_type"] == "primary" and item["is_active"]
            for item in payload
        )
        assert any(
            item["dataset_type"] == "knowledge" and item["is_active"]
            for item in payload
        )
