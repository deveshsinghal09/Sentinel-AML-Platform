"""Reusable execution budgets for model scoring and explanation rendering."""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Any


class ExecutionBudgetExceeded(RuntimeError):
    """Raised when a bounded agent operation exceeds a declared limit."""


@dataclass(frozen=True, slots=True)
class ExecutionBudget:
    max_model_rows: int = 25_000
    max_model_features: int = 64
    max_explanations: int = 100
    max_explanation_chars: int = 2_000
    total_seconds: float = 15.0

    def __post_init__(self):
        if self.max_model_rows < 1:
            raise ValueError("max_model_rows must be positive")
        if self.max_model_features < 1:
            raise ValueError("max_model_features must be positive")
        if self.max_explanations < 1:
            raise ValueError("max_explanations must be positive")
        if self.max_explanation_chars < 80:
            raise ValueError("max_explanation_chars must be at least 80")
        if self.total_seconds <= 0:
            raise ValueError("total_seconds must be positive")


class ExecutionDeadline:
    """Cooperative monotonic deadline suitable for deterministic tests."""

    def __init__(
        self,
        seconds: float,
        *,
        clock: Callable[[], float] = monotonic,
    ):
        if seconds <= 0:
            raise ValueError("deadline seconds must be positive")
        self._clock = clock
        self._expires_at = clock() + seconds

    def checkpoint(self, operation: str) -> None:
        if self._clock() > self._expires_at:
            raise ExecutionBudgetExceeded(
                f"{operation} exceeded the execution deadline"
            )


class BoundedModelExecutor:
    """Validate the model boundary before and after an injected scorer call."""

    def __init__(self, budget: ExecutionBudget | None = None):
        self.budget = budget or ExecutionBudget()

    def score(
        self,
        rows: Sequence[Mapping[str, Any]],
        scorer: Callable[
            [Sequence[Mapping[str, Any]], ExecutionDeadline],
            Sequence[float],
        ],
        *,
        clock: Callable[[], float] = monotonic,
    ) -> list[float]:
        if len(rows) > self.budget.max_model_rows:
            raise ExecutionBudgetExceeded(
                f"model input exceeds {self.budget.max_model_rows} rows"
            )
        if any(len(row) > self.budget.max_model_features for row in rows):
            raise ExecutionBudgetExceeded(
                f"model input exceeds {self.budget.max_model_features} features"
            )
        deadline = ExecutionDeadline(self.budget.total_seconds, clock=clock)
        deadline.checkpoint("model scoring")
        raw_scores = list(scorer(rows, deadline))
        deadline.checkpoint("model scoring")
        if len(raw_scores) != len(rows):
            raise ValueError("model scorer must return one score per input row")
        if any(
            not math.isfinite(float(score)) or not 0 <= float(score) <= 1
            for score in raw_scores
        ):
            raise ValueError("model scores must be finite values between 0 and 1")
        return [float(score) for score in raw_scores]


class BoundedExplanationExecutor:
    """Render a capped number of bounded explanations under one deadline."""

    def __init__(self, budget: ExecutionBudget | None = None):
        self.budget = budget or ExecutionBudget()

    def render(
        self,
        entities: Sequence[Mapping[str, Any]],
        renderer: Callable[[Mapping[str, Any]], str],
        *,
        clock: Callable[[], float] = monotonic,
    ) -> list[str]:
        if len(entities) > self.budget.max_explanations:
            raise ExecutionBudgetExceeded(
                f"explanation input exceeds {self.budget.max_explanations} entities"
            )
        deadline = ExecutionDeadline(self.budget.total_seconds, clock=clock)
        explanations: list[str] = []
        for entity in entities:
            deadline.checkpoint("explanation rendering")
            text = " ".join(str(renderer(entity)).split())
            if len(text) > self.budget.max_explanation_chars:
                text = text[: self.budget.max_explanation_chars - 1].rstrip() + "…"
            explanations.append(text)
        deadline.checkpoint("explanation rendering")
        return explanations
