"""Policy-bounded dynamic planner for natural-language AML investigations."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from agent.models import IntentFilters, IntentResult, SkippedTool
from agent.orchestration.contracts import (
    AdaptiveExecutionPlan,
    PlannedTool,
    ToolName,
)


_GRAPH_PATTERNS = {
    "layering",
    "cycle",
    "fan_in",
    "fan_out",
    "bipartite",
    "gather_scatter",
    "scatter_gather",
}
_STATISTICAL_PATTERNS = {
    "behavioural_change",
    "rapid_cashout",
    "single_large",
}
_ALL_OPTIONAL_TOOLS: tuple[ToolName, ...] = (
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
)


@dataclass(frozen=True, slots=True)
class PlanningLimits:
    """Hard limits enforced before a plan reaches the runtime."""

    max_steps: int = 8
    max_records: int = 100_000

    def __post_init__(self):
        if self.max_steps < 2:
            raise ValueError("max_steps must be at least 2")
        if self.max_records < 1:
            raise ValueError("max_records must be positive")


def _filter_parameters(filters: IntentFilters) -> dict[str, object]:
    """Return only explicit user filters, ready for the data-loading boundary."""

    return filters.model_dump(exclude_none=True)


class DynamicPlanningAgent:
    """Construct the smallest defensible plan for a validated intent.

    Intent extraction is deliberately separate. This class makes tool-selection
    decisions only from the validated intent contract, keeping planning
    deterministic, testable, and safe to audit.
    """

    def __init__(self, limits: PlanningLimits | None = None):
        self.limits = limits or PlanningLimits()

    def build_plan(
        self,
        query: str,
        intent: IntentResult,
    ) -> AdaptiveExecutionPlan:
        normalized_query = " ".join(query.split())
        if not normalized_query:
            raise ValueError("query cannot be blank")

        steps: list[PlannedTool] = [
            PlannedTool(
                tool="data_loader",
                reason="Load only the evidence required by the extracted filters.",
                parameters={
                    "filters": _filter_parameters(intent.filters),
                    "entity_ids": intent.entities,
                    "max_records": self.limits.max_records,
                },
            )
        ]
        rationale: str

        if intent.intent == "aggregation":
            steps.append(
                PlannedTool(
                    tool="aggregation",
                    reason="Answer the count or threshold question directly.",
                    parameters={
                        "min_count": intent.filters.min_count,
                        "max_amount": intent.filters.max_amount,
                    },
                )
            )
            rationale = (
                "A deterministic aggregation directly answers this threshold "
                "query; exploratory and anomaly tools would add noise."
            )
        elif intent.intent == "entity_lookup":
            steps.extend(
                [
                    PlannedTool(
                        tool="entity_lookup",
                        reason="Retrieve evidence for the requested entity only.",
                        parameters={
                            "entity_id": intent.filters.entity_id
                            or (intent.entities[0] if intent.entities else None)
                        },
                    ),
                    PlannedTool(
                        tool="risk_engine",
                        reason="Classify the entity's current evidence.",
                    ),
                    PlannedTool(
                        tool="knowledge_retriever",
                        reason="Ground any explanation in the relevant typology.",
                    ),
                ]
            )
            rationale = (
                "A single-entity lookup uses existing evidence and on-demand "
                "risk classification without running broad EDA."
            )
        elif intent.intent == "broad_eda":
            steps.extend(
                [
                    PlannedTool(
                        tool="eda",
                        reason="The request asks for broad dataset exploration.",
                    ),
                    PlannedTool(
                        tool="feature_engineering",
                        reason="Create baseline AML behavioural features.",
                    ),
                    PlannedTool(
                        tool="statistical_engine",
                        reason="Surface distributional outliers in the baseline.",
                    ),
                    PlannedTool(
                        tool="ml_engine",
                        reason="Rank multivariate anomalies across the broad slice.",
                    ),
                    PlannedTool(
                        tool="risk_engine",
                        reason="Convert detector evidence into risk bands.",
                    ),
                ]
            )
            rationale = (
                "A broad exploration requires profiling and complementary "
                "statistical and ML signals."
            )
        else:
            steps.extend(self._pattern_steps(intent))
            rationale = self._pattern_rationale(intent)

        selected = {step.tool for step in steps}
        skipped = [
            SkippedTool(tool=tool, reason=self._skip_reason(tool, intent))
            for tool in _ALL_OPTIONAL_TOOLS
            if tool not in selected
        ]
        if len(steps) > self.limits.max_steps:
            raise ValueError(
                f"execution plan exceeds the {self.limits.max_steps}-step limit"
            )
        return AdaptiveExecutionPlan(
            query=normalized_query,
            intent=intent,
            steps=steps,
            skipped=skipped,
            rationale=rationale,
        )

    def _pattern_steps(self, intent: IntentResult) -> Iterable[PlannedTool]:
        pattern = intent.pattern_type
        steps = [
            PlannedTool(
                tool="feature_engineering",
                reason=f"Create only the features needed for {pattern or 'anomaly'} detection.",
                parameters={"pattern": pattern},
            ),
            PlannedTool(
                tool="rule_engine",
                reason="Apply explicit, reviewer-auditable AML rules.",
                parameters={"pattern": pattern},
            ),
        ]
        if pattern in _STATISTICAL_PATTERNS:
            steps.append(
                PlannedTool(
                    tool="statistical_engine",
                    reason="This pattern depends on peer or baseline deviation.",
                    parameters={"pattern": pattern},
                )
            )
        if intent.require_ml:
            steps.append(
                PlannedTool(
                    tool="ml_engine",
                    reason="The validated request requires multivariate anomaly scoring.",
                    parameters={"pattern": pattern},
                )
            )
        if intent.require_graph or pattern in _GRAPH_PATTERNS:
            steps.append(
                PlannedTool(
                    tool="graph_engine",
                    reason="The target typology requires counterparty-network evidence.",
                    parameters={"pattern": pattern},
                )
            )
        steps.extend(
            [
                PlannedTool(
                    tool="risk_engine",
                    reason="Combine the selected detector evidence into a risk decision.",
                ),
                PlannedTool(
                    tool="knowledge_retriever",
                    reason="Ground explanations in the target AML typology.",
                    parameters={"pattern": pattern},
                ),
            ]
        )
        return steps

    @staticmethod
    def _pattern_rationale(intent: IntentResult) -> str:
        pattern = intent.pattern_type or "suspicious activity"
        return (
            f"Targeted {pattern} analysis uses pattern-specific features and "
            "only the detector families justified by the request."
        )

    @staticmethod
    def _skip_reason(tool: str, intent: IntentResult) -> str:
        if tool == "eda":
            return "Broad profiling is unnecessary for this targeted request."
        if tool == "ml_engine":
            return "ML was not requested and deterministic evidence is sufficient."
        if tool == "graph_engine":
            return "The selected pattern does not require network topology."
        if tool == "statistical_engine":
            return "The selected pattern does not depend on baseline deviation."
        if tool == "aggregation":
            return "The request is not a direct count or threshold aggregation."
        if tool == "entity_lookup":
            return "No single-entity lookup was requested."
        return f"{tool} is not required for the extracted intent."
