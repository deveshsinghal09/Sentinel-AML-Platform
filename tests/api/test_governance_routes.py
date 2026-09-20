from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.monitoring.drift_monitor import ModelDriftMonitor, population_stability_index
from api.routes import governance
from api.services.auth_service import AuthSession, AuthUser
from api.services.governance_service import (
    MODEL_ID,
    EmptyDriftSnapshotProvider,
    GovernanceService,
)


SESSION = AuthSession(
    user=AuthUser(
        user_id="usr-supervisor",
        email="supervisor@bank.test",
        display_name="Sam Supervisor",
        roles=["supervisor"],
    ),
    expires_at="2026-07-27T10:00:00Z",
)


def _client(service, session=SESSION):
    app = FastAPI()
    app.include_router(governance.router)
    app.dependency_overrides[governance.get_governance_service] = lambda: service
    app.dependency_overrides[governance.require_governance_session] = lambda: session
    return TestClient(app)


def test_policy_and_model_card_are_versioned_read_only_contracts():
    service = GovernanceService(EmptyDriftSnapshotProvider())
    with _client(service) as client:
        policy = client.get("/governance/policy")
        model = client.get(f"/governance/models/{MODEL_ID}")

    assert policy.status_code == 200
    assert policy.headers["cache-control"] == "private, no-store"
    assert policy.json()["mode"] == "read_only"
    assert policy.json()["thresholds"] == {"medium": 0.45, "high": 0.75}
    assert model.json()["algorithm"] == "Isolation Forest"
    assert model.json()["drift_status"] == "not_evaluated"
    assert model.json()["random_state"] == 42


def test_missing_snapshot_is_disclosed_instead_of_faking_stability():
    service = GovernanceService(EmptyDriftSnapshotProvider())
    with _client(service) as client:
        response = client.get(f"/governance/models/{MODEL_ID}/drift")

    assert response.status_code == 200
    assert response.json()["status"] == "not_evaluated"
    assert response.json()["overall_psi"] is None
    assert "No governed current-batch" in response.json()["interpretation"]


def test_unknown_model_has_safe_404():
    service = GovernanceService(EmptyDriftSnapshotProvider())
    with _client(service) as client:
        response = client.get("/governance/models/private-model")

    assert response.status_code == 404
    assert "private-model" not in response.text


def test_drift_monitor_detects_material_distribution_shift():
    report = ModelDriftMonitor().evaluate(
        MODEL_ID,
        {"velocity_1hr": list(range(100))},
        {"velocity_1hr": [value + 500 for value in range(100)]},
    )

    assert report.status == "drift"
    assert report.overall_psi is not None
    assert report.overall_psi >= 0.20
    assert report.features[0].status == "drift"
    assert "not model accuracy" in report.interpretation


def test_psi_rejects_unusable_or_unbounded_input():
    with pytest.raises(ValueError, match="at least two"):
        population_stability_index([1], [1, 2])
    with pytest.raises(ValueError, match="between 2 and 50"):
        population_stability_index([1, 2], [1, 2], buckets=51)
