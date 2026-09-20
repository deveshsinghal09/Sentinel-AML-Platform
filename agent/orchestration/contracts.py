"""Typed contracts for adaptive AML execution plans."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.models import IntentResult, PlanResult, SkippedTool


ToolName = Literal[
    "data_loader",
    "eda",
    "entity_lookup",
    "aggregation",
    "feature_engineering",
    "rule_engine",
    "statistical_engine",
    "ml_engine",
    "graph_engine",
    "risk_engine",
    "knowledge_retriever",
]


class PlannedTool(BaseModel):
    """One bounded tool invocation in an agent-generated execution plan."""

    model_config = ConfigDict(extra="forbid")

    tool: ToolName
    reason: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class AdaptiveExecutionPlan(BaseModel):
    """Inspectable plan that records selected and deliberately skipped tools."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    intent: IntentResult
    steps: list[PlannedTool] = Field(min_length=1)
    skipped: list[SkippedTool] = Field(default_factory=list)
    rationale: str = Field(min_length=1)

    def selected_tools(self) -> tuple[str, ...]:
        return tuple(step.tool for step in self.steps)

    def as_api_contract(self) -> PlanResult:
        """Convert the richer internal plan to the stable API contract."""

        return PlanResult(
            steps=list(self.selected_tools()),
            skipped=self.skipped,
            reasoning=self.rationale,
        )
