from __future__ import annotations

from agent.interaction.query_clarifier import QueryClarificationAgent


def test_complete_targeted_query_is_ready_without_unnecessary_questions():
    result = QueryClarificationAgent().assess(
        "Find structuring in June",
        {
            "intent": "pattern_search",
            "pattern_type": "structuring",
            "dataset_id": "primary-v1",
            "filters": {"date_range": ["2026-06-01", "2026-06-30"]},
        },
    )

    assert result.status == "ready"
    assert result.questions == []
    assert result.assumptions == []


def test_missing_pattern_asks_one_controlled_question():
    result = QueryClarificationAgent().assess(
        "Find suspicious patterns",
        {
            "intent": "pattern_search",
            "filters": {},
        },
    )

    assert result.status == "needs_clarification"
    assert [question.field for question in result.questions] == ["pattern_type"]
    assert "structuring" in result.questions[0].options
    assert len(result.assumptions) == 2


def test_entity_lookup_requires_an_entity_but_not_optional_date_filter():
    result = QueryClarificationAgent().assess(
        "Is this customer suspicious?",
        {"intent": "entity_lookup", "filters": {}},
    )

    assert [question.field for question in result.questions] == ["entity_id"]


def test_blank_query_does_not_echo_untrusted_whitespace():
    result = QueryClarificationAgent().assess(" \n\t ")

    assert result.normalized_query == ""
    assert result.questions[0].prompt == (
        "What AML question should Sentinel investigate?"
    )
