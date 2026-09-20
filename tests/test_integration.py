from __future__ import annotations

import pytest

from agent.runner import AgentRunner


pytestmark = [pytest.mark.integration, pytest.mark.requires_data]


def test_structuring_pipeline_end_to_end():
    runner = AgentRunner(use_llm=False, max_rows=500)
    response = runner.run(
        "Find structuring patterns between 2022-09-01 and 2022-09-18"
    )
    assert response.plan.steps[0] == "data_loader"
    assert response.plan.steps[-1] == "explanation"
    skipped = {
        step.tool for step in response.execution_trace if step.status == "skipped"
    }
    assert {"eda", "graph_tool"}.issubset(skipped)
    assert response.summary_stats.total_analyzed > 0
    assert all(0 <= entity.risk_score <= 1 for entity in response.top_entities)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "The fixed HI-Small dataset ends in 2022; a relative last-30-days "
        "query in 2026 correctly returns no rows."
    ),
)
def test_plan_example_recent_window_contains_data():
    response = AgentRunner(use_llm=False, max_rows=500).run(
        "Find structuring patterns in the last 30 days"
    )
    assert response.summary_stats.total_analyzed > 0


def test_aggregation_pipeline_skips_ml_and_features():
    response = AgentRunner(use_llm=False, max_rows=500).run(
        "Which customers made 10+ transactions under $10,000?"
    )
    ran = {
        step.tool for step in response.execution_trace if step.status == "run"
    }
    assert "feature_engineering" not in ran
    assert "ml_engine" not in ran
    assert "eda" not in ran


def test_entity_lookup_scoped_to_single_account():
    response = AgentRunner(use_llm=False, max_rows=500).run(
        "Is customer ID 4521 suspicious?"
    )
    assert response.intent.intent == "entity_lookup"
    assert response.intent.entities == ["4521"]
    assert response.intent.filters.entity_id == "4521"


def test_broad_eda_invokes_eda_tool():
    response = AgentRunner(use_llm=False, max_rows=500).run(
        "Analyse this dataset for suspicious activity"
    )
    ran = {
        step.tool for step in response.execution_trace if step.status == "run"
    }
    assert "eda" in ran
    assert response.eda_summary is not None
    assert response.charts is not None


def test_plan_is_deterministic_for_same_query():
    runner = AgentRunner(use_llm=False, max_rows=100)
    query = "Find structuring patterns between 2022-09-01 and 2022-09-18"
    first = runner.run(query)
    second = runner.run(query)
    assert first.plan.steps == second.plan.steps
    assert [item.tool for item in first.plan.skipped] == [
        item.tool for item in second.plan.skipped
    ]
