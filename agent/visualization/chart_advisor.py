"""Select reviewer-useful charts from the evidence returned by an agent run."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent.visualization.contracts import (
    ChartRecommendation,
    VisualizationAdvice,
)


class VisualizationAdvisorAgent:
    """Recommend a small chart suite without inventing unavailable fields."""

    def advise(
        self,
        response: Mapping[str, Any],
        *,
        max_charts: int = 4,
    ) -> VisualizationAdvice:
        if max_charts < 1 or max_charts > 6:
            raise ValueError("max_charts must be between 1 and 6")

        candidates: list[ChartRecommendation] = []
        skipped: list[str] = []
        entities = response.get("top_entities")
        trace = response.get("execution_trace")
        aggregation = response.get("aggregation")
        graph = response.get("graph")
        eda = response.get("eda_summary")

        if isinstance(entities, list) and entities:
            candidates.extend(
                [
                    ChartRecommendation(
                        chart_id="suspicious-results",
                        kind="table",
                        title="Ranked suspicious entities",
                        reason=(
                            "A table preserves exact scores, reasons, and "
                            "recommended actions for analyst review."
                        ),
                        source_fields=(
                            "top_entities.entity_id",
                            "top_entities.risk_score",
                            "top_entities.risk_label",
                            "top_entities.explanation",
                            "top_entities.escalation_action",
                        ),
                        priority=5,
                    ),
                    ChartRecommendation(
                        chart_id="risk-distribution",
                        kind="bar",
                        title="Flagged entities by risk level",
                        reason="Show the balance of low, medium, and high alerts.",
                        source_fields=("top_entities.risk_label",),
                        priority=4,
                    ),
                ]
            )
            if self._has_transaction_timestamps(entities):
                candidates.append(
                    ChartRecommendation(
                        chart_id="activity-timeline",
                        kind="timeline",
                        title="Flagged transaction activity over time",
                        reason="Expose velocity and clustering in the evidence window.",
                        source_fields=(
                            "top_entities.top_transactions.timestamp",
                            "top_entities.top_transactions.amount",
                        ),
                        priority=4,
                    )
                )
            else:
                skipped.append(
                    "Activity timeline skipped: no transaction timestamps were returned."
                )

        if isinstance(aggregation, Mapping) and aggregation.get("rows"):
            candidates.append(
                ChartRecommendation(
                    chart_id="aggregation-results",
                    kind="table",
                    title="Threshold aggregation results",
                    reason=(
                        "The query asks for exact grouped counts, so a sortable "
                        "table is more defensible than an anomaly chart."
                    ),
                    source_fields=(
                        "aggregation.rows.entity_id",
                        "aggregation.rows.txn_count",
                        "aggregation.rows.total_amount",
                    ),
                    priority=5,
                )
            )

        if isinstance(graph, Mapping) and graph.get("status") == "ok":
            candidates.append(
                ChartRecommendation(
                    chart_id="counterparty-network",
                    kind="network",
                    title="Counterparty movement network",
                    reason="Network evidence is present for a relationship typology.",
                    source_fields=("graph.nodes", "graph.edges"),
                    priority=5,
                )
            )
        else:
            skipped.append(
                "Network skipped: the execution path returned no graph evidence."
            )

        if isinstance(eda, Mapping) and eda:
            candidates.append(
                ChartRecommendation(
                    chart_id="dataset-profile",
                    kind="metric_cards",
                    title="Selected dataset profile",
                    reason="Broad EDA metrics provide context for the analyzed slice.",
                    source_fields=("eda_summary",),
                    priority=3,
                )
            )

        if isinstance(trace, list) and trace:
            candidates.append(
                ChartRecommendation(
                    chart_id="tool-execution",
                    kind="bar",
                    title="Agent tool execution",
                    reason="Make selected and skipped tool behavior easy to inspect.",
                    source_fields=(
                        "execution_trace.tool",
                        "execution_trace.status",
                        "execution_trace.duration_ms",
                    ),
                    priority=3,
                )
            )

        selected = sorted(
            candidates,
            key=lambda item: -item.priority,
        )[:max_charts]
        return VisualizationAdvice(
            recommendations=selected,
            skipped=skipped,
        )

    @staticmethod
    def _has_transaction_timestamps(entities: list[Any]) -> bool:
        for entity in entities:
            if not isinstance(entity, Mapping):
                continue
            transactions = entity.get("top_transactions")
            if not isinstance(transactions, list):
                continue
            if any(
                isinstance(transaction, Mapping)
                and bool(transaction.get("timestamp"))
                for transaction in transactions
            ):
                return True
        return False
