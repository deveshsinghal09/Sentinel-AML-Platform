from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import dashboard


class FakeDashboardRepository:
    def list_datasets(self):
        return [
            {
                "dataset_id": "primary-v1",
                "display_name": "Primary evidence",
                "dataset_type": "primary",
                "row_count": 20_000,
                "date_min": "2022-09-01",
                "date_max": "2022-09-30",
                "schema_version": "1.0",
                "is_active": True,
            },
            {
                "dataset_id": "knowledge-v1",
                "display_name": "AML typologies",
                "dataset_type": "knowledge",
                "row_count": 5_000,
                "date_min": None,
                "date_max": None,
                "schema_version": "1.0",
                "is_active": True,
            },
            {
                "dataset_id": "primary-archive",
                "display_name": "Archived evidence",
                "dataset_type": "primary",
                "row_count": 3_000,
                "schema_version": "1.0",
                "is_active": False,
            },
        ]

    def workflow_snapshot(self):
        return {
            "queue": {
                "total": 9,
                "new": 4,
                "in_review": 2,
                "escalated": 2,
                "closed": 1,
            },
            "investigations": [
                {"investigation_id": "inv-1", "high_risk_count": 2},
                {"investigation_id": "inv-2", "high_risk_count": 1},
            ],
        }


def _client(repository):
    app = FastAPI()
    app.include_router(dashboard.router)
    app.dependency_overrides[dashboard.get_dashboard_repository] = (
        lambda: repository
    )
    return TestClient(app)


def test_dashboard_summary_is_bounded_reviewer_facing_and_reconcilable():
    with _client(FakeDashboardRepository()) as client:
        response = client.get("/dashboard/summary")

    payload = response.json()
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert payload["generated_at"].endswith("Z")
    assert payload["datasets"] == {
        "registered": 3,
        "active": 2,
        "governed_rows": 28_000,
        "active_primary": {
            "dataset_id": "primary-v1",
            "display_name": "Primary evidence",
            "dataset_type": "primary",
            "row_count": 20_000,
            "date_min": "2022-09-01",
            "date_max": "2022-09-30",
            "schema_version": "1.0",
        },
        "active_knowledge": {
            "dataset_id": "knowledge-v1",
            "display_name": "AML typologies",
            "dataset_type": "knowledge",
            "row_count": 5_000,
            "date_min": None,
            "date_max": None,
            "schema_version": "1.0",
        },
    }
    assert payload["workload"] == {
        "status": "available",
        "investigations": 2,
        "high_risk_entities": 3,
        "alerts": 9,
        "new": 4,
        "in_review": 2,
        "escalated": 2,
        "closed": 1,
    }
    assert "transaction" not in payload
    assert "analyst" in payload["decision_notice"]


def test_dashboard_identifies_workflow_that_is_not_configured():
    repository = FakeDashboardRepository()
    repository.workflow_snapshot = lambda: None

    with _client(repository) as client:
        response = client.get("/dashboard/summary")

    assert response.status_code == 200
    assert response.json()["workload"] == {
        "status": "not_configured",
        "investigations": 0,
        "high_risk_entities": 0,
        "alerts": 0,
        "new": 0,
        "in_review": 0,
        "escalated": 0,
        "closed": 0,
    }


def test_dashboard_dependency_failure_is_generic_and_non_cacheable():
    class FailingRepository(FakeDashboardRepository):
        def list_datasets(self):
            raise RuntimeError("D:/bank/private/evidence.duckdb")

    with _client(FailingRepository()) as client:
        response = client.get("/dashboard/summary")

    assert response.status_code == 503
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "detail": "The command-center summary is temporarily unavailable."
    }
    assert "evidence.duckdb" not in response.text
