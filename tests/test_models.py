from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent.models import (
    AgentResponse,
    FlaggedEntity,
    IntentFilters,
    IntentResult,
    PlanResult,
    QueryRequest,
)


def test_intent_filters_rejects_inverted_amount_range():
    with pytest.raises(ValidationError):
        IntentFilters(min_amount=100, max_amount=99)


def test_intent_filters_require_ordered_iso_date_range():
    with pytest.raises(ValidationError, match="ISO"):
        IntentFilters(date_range=("09/01/2022", "2022-09-18"))
    with pytest.raises(ValidationError, match="cannot be after"):
        IntentFilters(date_range=("2022-09-18", "2022-09-01"))


def test_intent_result_default_flags_are_false():
    result = IntentResult(intent="aggregation")
    assert not result.require_ml
    assert not result.require_graph
    assert not result.require_eda


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_flagged_entity_risk_score_bounds(score):
    with pytest.raises(ValidationError):
        FlaggedEntity(
            entity_id="A",
            risk_score=score,
            risk_label="low",
            escalation_action="monitor",
        )


def test_agent_response_serialises_to_json():
    response = AgentResponse(
        query="analyse",
        intent=IntentResult(intent="broad_eda"),
        plan=PlanResult(steps=["data_loader", "eda"], reasoning="EDA"),
        execution_trace=[],
    )
    payload = json.loads(response.model_dump_json())
    assert payload["query"] == "analyse"
    assert payload["summary_stats"]["total_analyzed"] == 0


def test_query_request_rejects_empty_string():
    with pytest.raises(ValidationError):
        QueryRequest(query="")


def test_query_request_rejects_oversized_string():
    with pytest.raises(ValidationError):
        QueryRequest(query="x" * 2_001)


def test_query_request_normalizes_whitespace_and_rejects_blank_values():
    assert QueryRequest(query="  Find   structuring \n activity  ").query == (
        "Find structuring activity"
    )
    with pytest.raises(ValidationError, match="blank"):
        QueryRequest(query=" \n\t ")
    with pytest.raises(ValidationError, match="dataset_id"):
        QueryRequest(query="Analyse data", dataset_id="   ")
