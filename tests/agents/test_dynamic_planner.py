from __future__ import annotations

from agent.models import IntentFilters, IntentResult
from agent.orchestration.dynamic_planner import DynamicPlanningAgent


def test_structuring_query_uses_targeted_rules_without_eda_or_ml():
    intent = IntentResult(
        intent="pattern_search",
        pattern_type="structuring",
        filters=IntentFilters(
            date_range=("2026-06-01", "2026-06-30"),
            max_amount=10_000,
        ),
    )

    plan = DynamicPlanningAgent().build_plan(
        "Find structuring in June under $10,000",
        intent,
    )

    assert plan.selected_tools() == (
        "data_loader",
        "feature_engineering",
        "rule_engine",
        "risk_engine",
        "knowledge_retriever",
    )
    assert plan.steps[0].parameters["filters"]["max_amount"] == 10_000
    assert {item.tool for item in plan.skipped} >= {"eda", "ml_engine"}
    assert plan.as_api_contract().steps == list(plan.selected_tools())


def test_direct_threshold_query_skips_all_anomaly_detectors():
    intent = IntentResult(
        intent="aggregation",
        filters=IntentFilters(max_amount=10_000, min_count=10),
    )

    plan = DynamicPlanningAgent().build_plan(
        "Which customers made 10 or more transactions under $10,000?",
        intent,
    )

    assert plan.selected_tools() == ("data_loader", "aggregation")
    assert {
        "rule_engine",
        "statistical_engine",
        "ml_engine",
        "graph_engine",
    }.isdisjoint(plan.selected_tools())


def test_graph_pattern_and_broad_eda_choose_different_tool_paths():
    planner = DynamicPlanningAgent()
    graph = planner.build_plan(
        "Find layering networks",
        IntentResult(
            intent="pattern_search",
            pattern_type="layering",
        ),
    )
    broad = planner.build_plan(
        "Explore this dataset for suspicious activity",
        IntentResult(intent="broad_eda"),
    )

    assert "graph_engine" in graph.selected_tools()
    assert "eda" not in graph.selected_tools()
    assert "eda" in broad.selected_tools()
    assert "ml_engine" in broad.selected_tools()
    assert "rule_engine" not in broad.selected_tools()


def test_blank_query_is_rejected_before_planning():
    try:
        DynamicPlanningAgent().build_plan(
            " \n ",
            IntentResult(intent="broad_eda"),
        )
    except ValueError as exc:
        assert str(exc) == "query cannot be blank"
    else:
        raise AssertionError("blank query should be rejected")
