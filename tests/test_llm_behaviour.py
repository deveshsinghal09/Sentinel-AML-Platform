from __future__ import annotations

import os

import pytest

from agent.intent_extractor import IntentExtractor
from agent.knowledge import get_knowledge
from agent.models import IntentResult
from agent.planner import DynamicPlanner


pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        not os.getenv("GROQ_API_KEY"),
        reason="GROQ_API_KEY is not configured",
    ),
]


def test_groq_intent_returns_valid_schema():
    result = IntentExtractor(use_llm=True).extract(
        "Find structuring patterns in the last 30 days"
    )
    assert result.intent == "pattern_search"
    assert result.pattern_type == "structuring"
    assert result.filters.date_range is not None


def test_groq_plan_differs_between_query_types():
    planner = DynamicPlanner(use_llm=True)
    knowledge = get_knowledge()
    pattern = IntentResult(
        intent="pattern_search",
        pattern_type="structuring",
        require_ml=True,
    )
    aggregation = IntentResult(intent="aggregation")
    first = planner.plan(pattern, knowledge.lookup("structuring"))
    second = planner.plan(aggregation, [])
    assert first.steps != second.steps
