from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from api.main import app


def test_drift_endpoint_returns_monitoring_contract(monkeypatch):
    monkeypatch.setattr(
        "tools.data_loader.load",
        lambda **_: pd.DataFrame({"amount_paid": [100.0]}),
    )
    monkeypatch.setattr(
        "tools.model_drift.compute_drift_report",
        lambda _: {
            "model_id": "sentinel-saml-iforest-v1",
            "method": "population_stability_index",
            "status": "stable",
            "overall_psi": 0.02,
            "thresholds": {"stable_below": 0.1, "drift_above": 0.2},
            "baseline_rows": 50_000,
            "current_rows": 1,
            "features": [],
            "compared_at": "2026-07-26T00:00:00Z",
            "interpretation": "Model owner review required.",
        },
    )
    with TestClient(app) as client:
        response = client.get("/model-card/drift?limit=100")
    assert response.status_code == 200
    assert response.json()["status"] == "stable"
    assert response.json()["current_dataset"].startswith("HI-Small")


def test_cors_is_restricted_to_configured_local_origins():
    with TestClient(app) as client:
        allowed = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        denied = client.options(
            "/health",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in denied.headers
