from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.models import (
    AgentResponse,
    IntentResult,
    PlanResult,
    QueryRequest,
    SummaryStats,
)
from api.routes import query
from api.services.auth_service import AuthSession, AuthUser
from api.services.query_service import (
    QueryCapacityError,
    QueryService,
    QueryValidationError,
)


SESSION = AuthSession(
    user=AuthUser(
        user_id="usr-analyst-1",
        email="analyst@institution.test",
        display_name="Avery Analyst",
        roles=["analyst"],
    ),
    expires_at="2026-07-27T10:00:00Z",
)


def _response(query_text):
    return AgentResponse(
        query=query_text,
        intent=IntentResult(
            intent="pattern_search",
            pattern_type="structuring",
        ),
        plan=PlanResult(
            steps=["data_loader", "rule_engine"],
            reasoning="Targeted structuring query; broad EDA is unnecessary.",
        ),
        execution_trace=[],
        summary_stats=SummaryStats(
            total_analyzed=120,
            flagged=2,
            high_risk=1,
        ),
    )


class FakeQueryService:
    def __init__(self):
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return _response(request.query)


def _client(service, session=SESSION):
    app = FastAPI()
    app.include_router(query.router)
    app.dependency_overrides[query.get_query_service] = lambda: service
    app.dependency_overrides[query.require_query_session] = lambda: session
    return TestClient(app)


def test_query_route_normalizes_input_and_returns_agent_trace_contract():
    service = FakeQueryService()
    with _client(service) as client:
        response = client.post(
            "/query",
            json={
                "query": "  Find   structuring in the last 30 days  ",
                "dataset_id": "primary-v1",
            },
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert service.requests == [
        QueryRequest(
            query="Find structuring in the last 30 days",
            dataset_id="primary-v1",
        )
    ]
    payload = response.json()
    assert payload["intent"]["pattern_type"] == "structuring"
    assert payload["plan"]["steps"] == ["data_loader", "rule_engine"]
    assert payload["summary_stats"]["high_risk"] == 1


def test_query_route_rejects_blank_and_extra_input_before_execution():
    service = FakeQueryService()
    with _client(service) as client:
        response = client.post(
            "/query",
            json={"query": "   ", "admin_override": True},
        )

    assert response.status_code == 422
    assert service.requests == []


def test_query_capacity_and_validation_errors_have_stable_responses():
    class CapacityService:
        def run(self, request):
            raise QueryCapacityError("internal semaphore state")

    class ValidationService:
        def run(self, request):
            raise QueryValidationError(
                "The query could not be executed for the selected evidence."
            )

    with _client(CapacityService()) as client:
        capacity = client.post("/query", json={"query": "Find anomalies"})
    with _client(ValidationService()) as client:
        validation = client.post("/query", json={"query": "Find anomalies"})

    assert capacity.status_code == 503
    assert capacity.headers["retry-after"] == "2"
    assert "semaphore" not in capacity.text
    assert validation.status_code == 422
    assert validation.json() == {
        "detail": (
            "The query could not be executed for the selected evidence."
        )
    }


def test_query_service_releases_capacity_after_executor_failure():
    class Executor:
        def __init__(self):
            self.calls = 0

        def run(self, query_text, dataset_id=None):
            self.calls += 1
            if self.calls == 1:
                raise ValueError("Dataset not found at a private path")
            return _response(query_text)

    executor = Executor()
    service = QueryService(executor, max_concurrent=1)

    try:
        service.run(QueryRequest(query="First query"))
    except QueryValidationError:
        pass
    result = service.run(QueryRequest(query="Second query"))

    assert result.query == "Second query"
    assert executor.calls == 2
