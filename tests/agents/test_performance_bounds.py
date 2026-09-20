from __future__ import annotations

import math

import pytest

from agent.models import IntentResult
from agent.orchestration.dynamic_planner import (
    DynamicPlanningAgent,
    PlanningLimits,
)
from agent.runtime.bounded_execution import (
    BoundedExplanationExecutor,
    BoundedModelExecutor,
    ExecutionBudget,
    ExecutionBudgetExceeded,
)


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def test_planner_publishes_row_limit_and_keeps_tool_path_bounded():
    planner = DynamicPlanningAgent(
        PlanningLimits(max_steps=7, max_records=12_500)
    )

    plan = planner.build_plan(
        "Find layering with graph and ML evidence",
        IntentResult(
            intent="pattern_search",
            pattern_type="layering",
            require_graph=True,
            require_ml=True,
        ),
    )

    assert len(plan.steps) == 7
    assert plan.steps[0].parameters["max_records"] == 12_500
    assert len(plan.selected_tools()) == len(set(plan.selected_tools()))


def test_model_row_limit_fails_before_scorer_is_called():
    calls = []
    executor = BoundedModelExecutor(
        ExecutionBudget(max_model_rows=2)
    )

    with pytest.raises(ExecutionBudgetExceeded, match="2 rows"):
        executor.score(
            [{"x": 1}, {"x": 2}, {"x": 3}],
            lambda rows, deadline: calls.append(rows) or [],
        )

    assert calls == []


def test_model_deadline_uses_injected_monotonic_clock():
    clock = Clock()
    executor = BoundedModelExecutor(
        ExecutionBudget(total_seconds=1)
    )

    def slow_scorer(rows, deadline):
        clock.value = 1.01
        return [0.5 for _ in rows]

    with pytest.raises(ExecutionBudgetExceeded, match="model scoring"):
        executor.score([{"x": 1}], slow_scorer, clock=clock)


@pytest.mark.parametrize("score", [math.nan, math.inf, -0.01, 1.01])
def test_model_output_requires_finite_normalized_scores(score):
    with pytest.raises(ValueError, match="between 0 and 1"):
        BoundedModelExecutor().score(
            [{"x": 1}],
            lambda rows, deadline: [score],
        )


def test_explanation_count_is_bounded_before_rendering():
    calls = []
    executor = BoundedExplanationExecutor(
        ExecutionBudget(max_explanations=1)
    )

    with pytest.raises(ExecutionBudgetExceeded, match="1 entities"):
        executor.render(
            [{"id": "A"}, {"id": "B"}],
            lambda entity: calls.append(entity) or "explanation",
        )

    assert calls == []


def test_explanation_text_is_normalized_and_capped():
    executor = BoundedExplanationExecutor(
        ExecutionBudget(max_explanation_chars=80)
    )

    result = executor.render(
        [{"id": "A"}],
        lambda entity: "  Evidence   " + ("x" * 100),
    )

    assert len(result[0]) == 80
    assert result[0].endswith("…")
    assert "  " not in result[0]
