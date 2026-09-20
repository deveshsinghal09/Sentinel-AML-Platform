"""Phase 2 intent, planning, runner, and API contract tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.intent_extractor import IntentExtractor
from agent.models import AgentResponse
from agent.planner import DynamicPlanner
from agent.runner import AgentRunner
from api.main import app


class FakeCompletions:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(self.payload)
                    )
                )
            ]
        )


def fake_client(payload):
    completions = FakeCompletions(payload)
    return (
        SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        ),
        completions,
    )


CANONICAL_CASES = [
    (
        "Find structuring patterns in the last 30 days",
        [
            "data_loader",
            "feature_engineering",
            "rule_engine",
            "statistical",
            "ml_engine",
            "risk_scorer",
            "escalation",
            "explanation",
        ],
        {"eda", "graph_tool"},
    ),
    (
        "Which customers made 10+ transactions under $10,000?",
        [
            "data_loader",
            "aggregation",
            "risk_scorer",
            "escalation",
            "explanation",
        ],
        {
            "eda",
            "feature_engineering",
            "statistical",
            "ml_engine",
            "graph_tool",
            "rule_engine",
        },
    ),
    (
        "Is customer ID 4521 suspicious?",
        [
            "data_loader",
            "feature_engineering",
            "rule_engine",
            "statistical",
            "risk_scorer",
            "escalation",
            "explanation",
        ],
        {"eda", "ml_engine", "graph_tool"},
    ),
    (
        "Analyse this dataset for suspicious activity",
        [
            "data_loader",
            "eda",
            "feature_engineering",
            "statistical",
            "ml_engine",
            "risk_scorer",
            "escalation",
            "explanation",
        ],
        {"rule_engine", "graph_tool"},
    ),
]


@pytest.fixture(scope="module")
def phase2_runner() -> AgentRunner:
    return AgentRunner(
        intent_extractor=IntentExtractor(use_llm=False),
        planner=DynamicPlanner(use_llm=False),
        max_rows=25,
    )


@pytest.mark.parametrize(
    ("query", "expected_steps", "expected_skips"),
    CANONICAL_CASES,
)
@pytest.mark.requires_data
def test_canonical_queries_have_required_distinct_plans(
    phase2_runner,
    query,
    expected_steps,
    expected_skips,
):
    response = phase2_runner.run(query)
    assert isinstance(response, AgentResponse)
    assert response.plan.steps == expected_steps

    skipped = {item.tool for item in response.plan.skipped}
    assert expected_skips.issubset(skipped)

    run_trace = [
        item.tool for item in response.execution_trace if item.status == "run"
    ]
    assert run_trace == expected_steps
    assert all(item.reason for item in response.execution_trace)


@pytest.mark.requires_data
def test_canonical_step_lists_are_all_different(phase2_runner):
    plans = {
        tuple(phase2_runner.run(query).plan.steps)
        for query, _, _ in CANONICAL_CASES
    }
    assert len(plans) == 4


def test_aggregation_extracts_threshold_not_entity():
    intent = IntentExtractor(use_llm=False).extract(
        "Which customers made 10+ transactions under $10,000?"
    )
    assert intent.intent == "aggregation"
    assert intent.pattern_type == "structuring"
    assert intent.filters.entity_id is None
    assert intent.filters.max_amount == 10_000
    assert intent.filters.min_count == 10
    assert intent.require_ml is False


def test_entity_lookup_extracts_customer_id():
    intent = IntentExtractor(use_llm=False).extract(
        "Is customer ID 4521 suspicious?"
    )
    assert intent.intent == "entity_lookup"
    assert intent.filters.entity_id == "4521"
    assert intent.entities == ["4521"]

    mixed_case = IntentExtractor(use_llm=False).extract(
        "Is customer ID 803D95360 suspicious?"
    )
    assert mixed_case.filters.entity_id == "803D95360"


def test_graph_is_selected_only_for_graph_pattern():
    extractor = IntentExtractor(use_llm=False)
    planner = DynamicPlanner(use_llm=False)
    layering = planner.plan(extractor.extract("Find layering patterns"))
    structuring = planner.plan(extractor.extract("Find structuring patterns"))
    assert "graph_tool" in layering.steps
    assert "graph_tool" not in structuring.steps


@pytest.mark.requires_data
def test_response_is_schema_complete_for_empty_entity(phase2_runner):
    response = phase2_runner.run("Is customer ID 4521 suspicious?")
    assert response.summary_stats.total_analyzed <= 25
    assert response.summary_stats.flagged == 0
    assert response.summary_stats.high_risk == 0
    assert response.top_entities == []
    assert any(
        "normalized risk" in step.reason
        for step in response.execution_trace
        if step.tool == "risk_scorer"
    )
    assert any(
        "grounded explanations" in step.reason
        for step in response.execution_trace
        if step.tool == "explanation"
    )


@pytest.mark.requires_data
def test_query_api_contract(phase2_runner):
    with TestClient(app) as client:
        app.state.agent_runner = phase2_runner
        app.state.workflow_enabled = False
        response = client.post(
            "/query",
            json={"query": "Is customer ID 4521 suspicious?"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["query"] == "Is customer ID 4521 suspicious?"
        assert payload["intent"]["intent"] == "entity_lookup"
        assert payload["plan"]["steps"] == CANONICAL_CASES[2][1]
        assert "execution_trace" in payload
        assert "top_entities" in payload
        assert "summary_stats" in payload
        app.state.workflow_enabled = True


def test_query_api_rejects_empty_query():
    with TestClient(app) as client:
        response = client.post("/query", json={"query": ""})
        assert response.status_code == 422


def test_health_reports_current_phase():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "phase": "C-advanced-quality",
        }


def test_intent_extractor_uses_groq_json_contract_when_enabled():
    client, completions = fake_client(
        {
            "intent": "pattern_search",
            "pattern_type": "layering",
            "filters": {
                "date_range": None,
                "entity_id": None,
                "from_country": None,
                "payment_format": None,
                "min_amount": None,
                "max_amount": None,
            },
            "entities": [],
            "require_ml": False,
            "require_graph": False,
            "require_eda": False,
        }
    )
    result = IntentExtractor(client=client, use_llm=True).extract(
        "Find layering patterns"
    )
    assert result.require_ml is True
    assert result.require_graph is True
    assert completions.calls[0]["model"] == "openai/gpt-oss-20b"
    assert completions.calls[0]["response_format"] == {
        "type": "json_object"
    }


def test_planner_normalizes_llm_tool_proposal_to_policy():
    client, completions = fake_client(
        {
            "steps": ["data_loader", "graph_tool", "explanation"],
            "skipped": [],
            "reasoning": "LLM proposal",
        }
    )
    intent = IntentExtractor(use_llm=False).extract(
        "Find structuring patterns"
    )
    plan = DynamicPlanner(client=client, use_llm=True).plan(intent)
    assert plan.steps == CANONICAL_CASES[0][1]
    assert completions.calls[0]["response_format"] == {
        "type": "json_object"
    }
