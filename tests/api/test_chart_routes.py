from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import charts


RECORD = {
    "investigation_id": "inv-001",
    "response": {
        "top_entities": [
            {"entity_id": "A", "risk_label": "high", "risk_score": 0.9},
            {"entity_id": "B", "risk_label": "medium", "risk_score": 0.6},
            {"entity_id": "C", "risk_label": "high", "risk_score": 0.8},
        ],
        "execution_trace": [
            {
                "tool": "data_loader",
                "status": "run",
                "duration_ms": 12.5,
            },
            {
                "tool": "eda",
                "status": "skipped",
                "duration_ms": 0,
            },
        ],
    },
}


class Repository:
    def get_investigation(self, investigation_id):
        return RECORD if investigation_id == "inv-001" else None


def _client(repository=None):
    app = FastAPI()
    app.include_router(charts.router)
    app.dependency_overrides[
        charts.get_investigation_repository
    ] = lambda: repository or Repository()
    return TestClient(app)


def test_chart_suite_reconciles_risk_and_execution_evidence():
    with _client() as client:
        response = client.get("/charts/investigations/inv-001")

    payload = response.json()
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert payload["investigation_id"] == "inv-001"
    risk, execution = payload["charts"]
    assert risk["data"][0]["x"] == ["low", "medium", "high"]
    assert risk["data"][0]["y"] == [0, 1, 2]
    assert risk["meta"]["record_count"] == 3
    assert execution["data"][0]["x"] == [12.5, 0]
    assert execution["meta"] == {
        "source": "execution_trace",
        "ran": 1,
        "skipped": 1,
    }


def test_chart_route_returns_404_for_missing_investigation():
    with _client() as client:
        response = client.get("/charts/investigations/inv-404")

    assert response.status_code == 404


def test_malformed_persisted_response_is_not_exposed():
    class MalformedRepository(Repository):
        def get_investigation(self, investigation_id):
            return {
                "investigation_id": investigation_id,
                "response": "private raw payload",
            }

    with _client(MalformedRepository()) as client:
        response = client.get("/charts/investigations/inv-001")

    assert response.status_code == 503
    assert "private raw payload" not in response.text
