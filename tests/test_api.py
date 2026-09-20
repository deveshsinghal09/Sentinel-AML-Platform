from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.models import AgentResponse
from agent.runner import AgentRunner
from api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        app.state.agent_runner = AgentRunner(use_llm=False, max_rows=100)
        app.state.workflow_enabled = False
        yield test_client
        app.state.workflow_enabled = True


def test_health_returns_expected_contract(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "phase" in response.json()


@pytest.mark.requires_data
def test_stats_returns_both_datasets_and_string_dates(client):
    response = client.get("/stats")
    assert response.status_code == 200
    payload = response.json()
    assert {"transactions", "saml_knowledge"}.issubset(payload)
    assert isinstance(payload["transactions"]["date_min"], str)


@pytest.fixture(scope="module")
def structuring_payload(client):
    response = client.post(
        "/query",
        json={"query": "Find structuring patterns between 2022-09-01 and 2022-09-18"},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.requires_data
def test_query_response_matches_agent_response_schema(structuring_payload):
    parsed = AgentResponse.model_validate(structuring_payload)
    assert parsed.execution_trace
    assert parsed.plan.steps[0] == "data_loader"
    assert parsed.plan.steps[-1] == "explanation"


@pytest.mark.requires_data
def test_query_trace_skips_eda_and_graph_for_structuring(structuring_payload):
    skipped = {
        step["tool"]
        for step in structuring_payload["execution_trace"]
        if step["status"] == "skipped"
    }
    assert {"eda", "graph_tool"}.issubset(skipped)


def test_query_rejects_empty_and_oversized_payloads(client):
    assert client.post("/query", json={"query": ""}).status_code == 422
    assert client.post("/query", json={"query": "x" * 2_001}).status_code == 422


@pytest.mark.requires_data
def test_schema_regression_fields_and_durations(structuring_payload):
    for step in structuring_payload["execution_trace"]:
        assert step["duration_ms"] >= 0
    assert "top_entities" in structuring_payload
    if structuring_payload["top_entities"]:
        entity = structuring_payload["top_entities"][0]
        assert "saml_d_typology" in entity
        assert "sar_draft" in entity
