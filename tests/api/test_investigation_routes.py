from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import investigations


RECORDS = [
    {
        "investigation_id": "inv-001",
        "dataset_id": "primary-v1",
        "dataset_name": "Primary evidence",
        "query": "Find structuring",
        "intent": "pattern_search",
        "pattern_type": "structuring",
        "status": "open",
        "disposition": "pending",
        "flagged_count": 4,
        "high_risk_count": 2,
        "alert_count": 4,
        "response": {"query": "Find structuring"},
        "created_at": "2026-07-26T09:00:00Z",
        "updated_at": "2026-07-26T09:00:00Z",
    },
    {
        "investigation_id": "inv-002",
        "dataset_id": "primary-v1",
        "dataset_name": "Primary evidence",
        "query": "Find layering",
        "intent": "pattern_search",
        "pattern_type": "layering",
        "status": "closed",
        "disposition": "false_positive",
        "flagged_count": 1,
        "high_risk_count": 0,
        "alert_count": 1,
        "response": {"query": "Find layering"},
        "created_at": "2026-07-25T09:00:00Z",
        "updated_at": "2026-07-25T11:00:00Z",
    },
]


class Repository:
    def list_investigations(self, *, limit, dataset_id):
        records = deepcopy(RECORDS)
        if dataset_id:
            records = [
                item for item in records if item["dataset_id"] == dataset_id
            ]
        return records[:limit]

    def get_investigation(self, investigation_id):
        return next(
            (
                deepcopy(item)
                for item in RECORDS
                if item["investigation_id"] == investigation_id
            ),
            None,
        )


def _client(repository=None):
    app = FastAPI()
    app.include_router(investigations.router)
    app.dependency_overrides[
        investigations.get_investigation_repository
    ] = lambda: repository or Repository()
    return TestClient(app)


def test_history_filters_without_returning_heavy_response_payloads():
    with _client() as client:
        response = client.get(
            "/investigations",
            params={"workflow_status": "open", "pattern_type": "structuring"},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert [item["investigation_id"] for item in response.json()] == [
        "inv-001"
    ]
    assert "response" not in response.json()[0]


def test_investigation_summary_reconciles_workload_counts():
    with _client() as client:
        response = client.get("/investigations/summary")

    assert response.status_code == 200
    assert response.json() == {
        "total": 2,
        "open": 1,
        "in_review": 0,
        "escalated": 0,
        "closed": 1,
        "high_risk_entities": 2,
        "alerts": 5,
    }


def test_detail_returns_structured_response_and_missing_is_404():
    with _client() as client:
        detail = client.get("/investigations/inv-001")
        missing = client.get("/investigations/inv-404")

    assert detail.status_code == 200
    assert detail.json()["response"]["query"] == "Find structuring"
    assert missing.status_code == 404


def test_repository_failure_is_generic():
    class FailingRepository(Repository):
        def list_investigations(self, *, limit, dataset_id):
            raise RuntimeError("D:/bank/private/workflow.duckdb")

    with _client(FailingRepository()) as client:
        response = client.get("/investigations")

    assert response.status_code == 503
    assert "workflow.duckdb" not in response.text
