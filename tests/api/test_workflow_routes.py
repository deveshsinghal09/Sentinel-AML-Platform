from __future__ import annotations

from datetime import UTC, datetime

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.repositories.workflow_repository import WorkflowRepository
from api.routes import workflow
from api.services.auth_service import AuthSession, AuthUser
from api.services.workflow_service import WorkflowNotFound


SESSION = AuthSession(
    user=AuthUser(
        user_id="usr-1",
        email="analyst@bank.test",
        display_name="Avery Analyst",
        roles=["analyst"],
    ),
    expires_at="2026-07-27T10:00:00Z",
)
ALERT = {
    "alert_id": "ALT-001",
    "entity_id": "ACC-17",
    "investigation_id": "INV-001",
    "risk_score": 0.88,
    "risk_label": "high",
    "escalation_action": "report",
    "typology": "structuring",
    "created_at": "2026-07-26T10:00:00Z",
    "sla_hours": 4,
    "assigned_to": None,
    "status": "new",
    "disposition": "pending",
    "notes": "",
    "age_hours": 2.0,
}


class Service:
    def __init__(self):
        self.calls = []

    def list_alerts(self, **kwargs):
        self.calls.append(("list", kwargs))
        return [ALERT], 1

    def summary(self):
        return {"total": 1, "new": 1, "in_review": 0, "escalated": 0, "closed": 0}

    def assign(self, alert_id, analyst, actor):
        self.calls.append(("assign", alert_id, analyst, actor))
        return {**ALERT, "assigned_to": analyst, "status": "in_review"}

    def disposition(self, alert_id, disposition, actor):
        self.calls.append(("disposition", alert_id, disposition, actor))
        return {**ALERT, "disposition": disposition}

    def append_note(self, alert_id, note, actor):
        self.calls.append(("note", alert_id, note, actor))
        return {**ALERT, "notes": note}

    def audit(self, **kwargs):
        return ([{"event_id": "AUD-1", "actor": "analyst@bank.test"}], 1)


def _client(service, session=SESSION):
    app = FastAPI()
    app.include_router(workflow.router)
    app.dependency_overrides[workflow.get_workflow_service] = lambda: service
    app.dependency_overrides[workflow.require_workflow_session] = lambda: session
    return TestClient(app)


def test_queue_filters_and_summary_are_bounded_and_private():
    service = Service()
    with _client(service) as client:
        page = client.get(
            "/workflow/queue",
            params={"workflow_status": "new", "limit": 25},
        )
        summary = client.get("/workflow/queue/summary")

    assert page.status_code == 200
    assert page.headers["cache-control"] == "private, no-store"
    assert page.json()["total"] == 1
    assert service.calls[0][1]["limit"] == 25
    assert summary.json()["new"] == 1


def test_mutations_use_authenticated_actor_not_request_supplied_identity():
    service = Service()
    with _client(service) as client:
        assigned = client.post(
            "/workflow/queue/ALT-001/assign",
            json={"assigned_to": "Devesh Reviewer"},
        )
        disposition = client.post(
            "/workflow/queue/ALT-001/disposition",
            json={"disposition": "escalated"},
        )
        note = client.post(
            "/workflow/queue/ALT-001/notes",
            json={"note": "  Verified   source transactions.  "},
        )

    assert assigned.json()["status"] == "in_review"
    assert service.calls[0][-1] == "analyst@bank.test"
    assert service.calls[1][-1] == "analyst@bank.test"
    assert service.calls[2] == (
        "note",
        "ALT-001",
        "Verified source transactions.",
        "analyst@bank.test",
    )
    assert disposition.status_code == note.status_code == 200


def test_extra_mutation_fields_and_invalid_transitions_are_rejected():
    service = Service()
    with _client(service) as client:
        extra = client.post(
            "/workflow/queue/ALT-001/assign",
            json={"assigned_to": "A", "actor": "spoofed@bank.test"},
        )
        invalid = client.post(
            "/workflow/queue/ALT-001/disposition",
            json={"disposition": "sar_filed"},
        )

    assert extra.status_code == 422
    assert invalid.status_code == 422
    assert service.calls == []


def test_missing_alert_and_store_failure_have_safe_errors():
    class Missing(Service):
        def assign(self, alert_id, analyst, actor):
            raise WorkflowNotFound("private database key")

    with _client(Missing()) as client:
        response = client.post(
            "/workflow/queue/ALT-404/assign",
            json={"assigned_to": "Avery"},
        )

    assert response.status_code == 404
    assert "database key" not in response.text


def test_repository_mutation_and_audit_commit_atomically(tmp_path):
    database = tmp_path / "workflow.duckdb"
    repository = WorkflowRepository(lambda: duckdb.connect(str(database)))
    repository.queue_summary()
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            INSERT INTO governed_alert_queue
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'new', 'pending', '')
            """,
            [
                "ALT-001",
                "ACC-17",
                "INV-001",
                0.88,
                "high",
                "report",
                "structuring",
                datetime.now(UTC).replace(tzinfo=None),
                4,
            ],
        )

    updated = repository.assign(
        "ALT-001",
        "Avery Analyst",
        "analyst@bank.test",
    )
    events, total = repository.list_audit(
        alert_id="ALT-001",
        limit=10,
        offset=0,
    )

    assert updated["assigned_to"] == "Avery Analyst"
    assert updated["status"] == "in_review"
    assert total == 1
    assert events[0]["event_type"] == "alert_assigned"
    assert events[0]["payload"] == {"assigned_to": "Avery Analyst"}
