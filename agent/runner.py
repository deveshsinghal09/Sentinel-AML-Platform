"""Central orchestrator for the AML agent pipeline."""
from __future__ import annotations

from time import perf_counter
from typing import Any

import pandas as pd

from agent.intent_extractor import IntentExtractor
from agent.knowledge import get_knowledge
from agent.models import (
    AgentResponse,
    AggregationResult,
    ExecutionStep,
    FlaggedEntity,
    IntentResult,
    PlanResult,
    RiskContribution,
    SummaryStats,
    TransactionEvidence,
)
from agent.planner import DynamicPlanner


class AgentRunner:
    """Extract intent, plan tools, execute them, and assemble a response."""

    def __init__(
        self,
        intent_extractor: IntentExtractor | None = None,
        planner: DynamicPlanner | None = None,
        max_rows: int = 1_000,
        use_llm: bool | None = None,
        explanation_generator: Any | None = None,
        dataset_id: str | None = None,
    ) -> None:
        if max_rows <= 0:
            raise ValueError("max_rows must be greater than zero")
        self.intent_extractor = intent_extractor or IntentExtractor(
            use_llm=use_llm
        )
        self.planner = planner or DynamicPlanner(use_llm=use_llm)
        self.max_rows = max_rows
        self.use_llm = use_llm
        self.explanation_generator = explanation_generator
        self.dataset_id = dataset_id

    def run(self, query: str, dataset_id: str | None = None) -> AgentResponse:
        """Run the complete Phase 2 orchestration path."""
        from tools.data_loader import get_db_connection
        from tools.dataset_store import resolve_dataset_context

        db = get_db_connection()
        try:
            resolved_id, dataset_name, _ = resolve_dataset_context(
                db,
                dataset_id or self.dataset_id,
            )
        finally:
            db.close()
        intent = self.intent_extractor.extract(query)
        knowledge_context = get_knowledge().lookup(
            intent.pattern_type or query,
            top_k=3,
        )
        plan = self.planner.plan(intent, knowledge_context)
        trace, results = self._execute(
            plan,
            intent,
            knowledge_context,
            resolved_id,
        )
        response = self._assemble_response(
            query=query,
            intent=intent,
            plan=plan,
            execution_trace=trace,
            results=results,
        )
        return response.model_copy(
            update={"dataset_id": resolved_id, "dataset_name": dataset_name}
        )

    def _execute(
        self,
        plan: PlanResult,
        intent: IntentResult,
        knowledge_context: list[dict],
        dataset_id: str | None = None,
    ) -> tuple[list[ExecutionStep], dict[str, Any]]:
        state: dict[str, Any] = {
            "df": pd.DataFrame(),
            "eda_summary": None,
            "charts": None,
            "graph": None,
            "aggregation": None,
            "ran_tools": set(plan.steps),
            "explanation_generator": self.explanation_generator,
            "dataset_id": dataset_id,
        }
        trace: list[ExecutionStep] = []

        for tool in plan.steps:
            started = perf_counter()
            reason = self._run_tool(tool, state, intent, knowledge_context)
            duration_ms = round((perf_counter() - started) * 1_000, 3)
            trace.append(
                ExecutionStep(
                    tool=tool,
                    status="run",
                    duration_ms=duration_ms,
                    reason=reason,
                )
            )

        trace.extend(
            ExecutionStep(
                tool=item.tool,
                status="skipped",
                duration_ms=0,
                reason=item.reason,
            )
            for item in plan.skipped
        )
        return trace, state

    def _run_tool(
        self,
        tool: str,
        state: dict[str, Any],
        intent: IntentResult,
        knowledge_context: list[dict],
    ) -> str:
        if tool == "data_loader":
            from tools.data_loader import load

            filters = intent.filters
            state["df"] = load(
                date_range=filters.date_range,
                entity_id=filters.entity_id,
                payment_format=filters.payment_format,
                min_amount=filters.min_amount,
                max_amount=filters.max_amount,
                limit=self.max_rows,
                dataset_id=state.get("dataset_id"),
            )
            country_note = (
                "; from_country deferred because HI-Small has no country column"
                if filters.from_country
                else ""
            )
            return (
                f"loaded {len(state['df']):,} transactions "
                f"(query safety cap {self.max_rows:,}){country_note}"
            )

        if tool == "aggregation":
            from tools.aggregation import run_aggregation

            filters = intent.filters
            result = run_aggregation(
                state["df"],
                min_count=filters.min_count or 1,
                max_amount=filters.max_amount,
                min_amount=filters.min_amount,
            )
            state["aggregation"] = result
            return (
                f"grouped {result.total_groups:,} accounts matching "
                "the explicit count and amount thresholds"
            )
        elif tool == "eda":
            from tools.eda import run_eda

            output = run_eda(
                state["df"],
                filters=intent.filters.model_dump(),
            )
            state["eda_summary"] = output["summary_stats"]
            state["charts"] = output["charts"]
            return (
                f"computed broad EDA over {len(state['df']):,} rows; "
                f"generated {len(state['charts']):,} Plotly-compatible charts"
            )
        elif tool == "feature_engineering":
            from tools.feature_engineering import (
                engineer_features,
                selected_feature_families,
            )

            patterns = [intent.pattern_type] if intent.pattern_type else None
            requires_model = "ml_engine" in state["ran_tools"]
            families = selected_feature_families(
                patterns,
                require_model_features=requires_model,
            )
            state["df"] = engineer_features(
                state["df"],
                patterns,
                require_model_features=requires_model,
            )
            feature_count = sum(
                column in state["df"].columns
                for column in {
                    "txn_count_7d",
                    "rolling_sum_7d",
                    "near_threshold_count",
                    "amount_deviation",
                    "velocity_1hr",
                    "fan_in_count",
                    "fan_in_sum_48h",
                    "fan_out_count",
                    "recent_inflow_24h",
                    "cross_border_flag",
                }
            )
            return (
                f"computed {feature_count} AML features from "
                f"{', '.join(families) or 'no derived families'} on "
                f"{len(state['df']):,} transactions"
            )
        elif tool == "rule_engine":
            from tools.rule_engine import run_rules

            patterns = [intent.pattern_type] if intent.pattern_type else None
            state["df"] = run_rules(state["df"], patterns)
            flagged = int(state["df"]["rule_flags"].map(bool).sum())
            return f"applied calibrated AML rules; {flagged:,} rows flagged"
        elif tool == "statistical":
            from tools.statistical import run_statistical

            state["df"] = run_statistical(state["df"])
            anomalous = int(state["df"]["stat_score"].gt(0).sum())
            return (
                "computed account z-scores and SAML-D normal IQR baseline; "
                f"{anomalous:,} rows scored above zero"
            )
        elif tool == "ml_engine":
            from tools.ml_engine import run_ml

            state["df"] = run_ml(
                state["df"],
                dataset_id=state.get("dataset_id"),
            )
            anomalies = int(state["df"]["anomaly_label"].sum())
            return (
                "applied SAML-D-trained Isolation Forest; "
                f"{anomalies:,} anomalies"
            )
        elif tool == "graph_tool":
            from tools.graph_tool import run_graph

            state["graph"] = run_graph(state["df"])
            graph_summary = state["graph"]["summary"]
            if state["graph"]["status"] == "skipped":
                return state["graph"]["note"]
            return (
                f"analyzed {graph_summary['nodes']:,} nodes and "
                f"{graph_summary['edges']:,} directed edges; found "
                f"{len(state['graph']['cycles']):,} bounded cycles"
            )
        elif tool == "risk_scorer":
            from tools.risk_scorer import score

            state["df"] = score(
                state["df"],
                ran_tools=state["ran_tools"],
            )
            medium_or_high = int(
                state["df"]["risk_label"].isin({"medium", "high"}).sum()
            )
            return (
                "normalized risk over detectors that ran; "
                f"{medium_or_high:,} rows medium/high"
            )
        elif tool == "escalation":
            from tools.escalation import recommend

            state["df"] = recommend(state["df"])
            review = int(
                state["df"]["escalation_action"].eq("flag_for_review").sum()
            )
            report = int(
                state["df"]["escalation_action"].eq("report").sum()
            )
            return (
                f"assigned escalation actions; {review:,} review, "
                f"{report:,} report"
            )
        elif tool == "explanation":
            from tools.explanation import ExplanationGenerator, explain

            state["df"] = explain(
                state["df"],
                intent.model_dump(),
                knowledge_context,
                generator=(
                    state["explanation_generator"]
                    or ExplanationGenerator(use_llm=self.use_llm)
                ),
            )
            explained = int(state["df"]["explanation"].ne("").sum())
            return (
                f"generated {explained:,} grounded explanations and SAR drafts"
            )
        else:
            raise ValueError(f"Unsupported validated tool: {tool}")

    @staticmethod
    def _assemble_response(
        query: str,
        intent: IntentResult,
        plan: PlanResult,
        execution_trace: list[ExecutionStep],
        results: dict[str, Any],
    ) -> AgentResponse:
        df: pd.DataFrame = results["df"]
        entities: list[FlaggedEntity] = []

        if not df.empty and "risk_score" in df:
            candidates = df.loc[df["risk_score"] >= 0.35].copy()
            candidates = candidates.sort_values(
                "risk_score",
                ascending=False,
                kind="stable",
            )
            if "from_account" in candidates:
                candidates = candidates.drop_duplicates("from_account")
            flagged_total = len(candidates)
            high_risk_total = int(candidates["risk_label"].eq("high").sum())
            for _, row in candidates.head(20).iterrows():
                entity_id = str(row.get("from_account", ""))
                raw_flags = row.get("rule_flags", [])
                rule_flags = (
                    list(raw_flags)
                    if isinstance(raw_flags, (list, tuple, set))
                    else []
                )
                entity_df = df.loc[
                    df.get(
                        "from_account",
                        pd.Series("", index=df.index),
                    ).astype("string")
                    == entity_id
                ].copy()
                if "amount_paid" in entity_df:
                    entity_df["__evidence_amount"] = pd.to_numeric(
                        entity_df["amount_paid"], errors="coerce"
                    ).fillna(0.0)
                    entity_df = entity_df.sort_values(
                        "__evidence_amount",
                        ascending=False,
                        kind="stable",
                    )

                top_transactions: list[TransactionEvidence] = []
                for index, evidence_row in entity_df.head(5).iterrows():
                    evidence_flags = evidence_row.get("rule_flags", [])
                    evidence_rule_flags = (
                        list(evidence_flags)
                        if isinstance(
                            evidence_flags,
                            (list, tuple, set),
                        )
                        else []
                    )
                    top_transactions.append(
                        TransactionEvidence(
                            txn_id=str(
                                evidence_row.get("txn_id", index)
                            ),
                            timestamp=str(
                                evidence_row.get("timestamp", "")
                            ),
                            amount=float(
                                evidence_row.get(
                                    "__evidence_amount",
                                    evidence_row.get("amount_paid", 0),
                                )
                            ),
                            payment_format=str(
                                evidence_row.get("payment_format", "")
                            ),
                            to_account=str(
                                evidence_row.get("to_account", "")
                            ),
                            from_country=(
                                str(evidence_row["from_country"])
                                if "from_country" in evidence_row
                                and pd.notna(evidence_row["from_country"])
                                else None
                            ),
                            to_country=(
                                str(evidence_row["to_country"])
                                if "to_country" in evidence_row
                                and pd.notna(evidence_row["to_country"])
                                else None
                            ),
                            triggered_rules=evidence_rule_flags,
                        )
                    )

                timestamps = pd.to_datetime(
                    entity_df.get(
                        "timestamp",
                        pd.Series(dtype="datetime64[ns]"),
                    ),
                    errors="coerce",
                )
                observation_window = (
                    (
                        timestamps.min().isoformat(),
                        timestamps.max().isoformat(),
                    )
                    if timestamps.notna().any()
                    else None
                )
                contribution_payload = row.get("risk_contribution")
                risk_contributions = (
                    RiskContribution.model_validate(contribution_payload)
                    if isinstance(contribution_payload, dict)
                    else None
                )
                entities.append(
                    FlaggedEntity(
                        entity_id=entity_id,
                        risk_score=float(row.get("risk_score", 0)),
                        risk_label=str(row.get("risk_label", "low")),
                        escalation_action=str(
                            row.get("escalation_action", "monitor")
                        ),
                        rule_flags=rule_flags,
                        rule_score=float(row.get("rule_score", 0)),
                        stat_score=float(row.get("stat_score", 0)),
                        ml_score=float(row.get("ml_score", 0)),
                        saml_d_typology=str(
                            row.get("saml_d_typology", "")
                        ),
                        explanation=str(row.get("explanation", "")),
                        sar_draft=str(row.get("sar_draft", "")),
                        citation=str(row.get("citation", "")),
                        risk_contributions=risk_contributions,
                        top_transactions=top_transactions,
                        txn_count=int(len(entity_df)),
                        total_amount=float(
                            pd.to_numeric(
                                entity_df.get(
                                    "amount_paid",
                                    pd.Series(dtype=float),
                                ),
                                errors="coerce",
                            ).sum()
                        ),
                        observation_window=observation_window,
                        distinct_counterparties=int(
                            entity_df["to_account"].nunique()
                            if "to_account" in entity_df
                            else 0
                        ),
                    )
                )
        else:
            flagged_total = 0
            high_risk_total = 0

        return AgentResponse(
            query=query,
            intent=intent,
            plan=plan,
            execution_trace=execution_trace,
            top_entities=entities,
            summary_stats=SummaryStats(
                total_analyzed=len(df),
                flagged=flagged_total,
                high_risk=high_risk_total,
            ),
            eda_summary=results.get("eda_summary"),
            charts=results.get("charts"),
            graph=results.get("graph"),
            aggregation=(
                AggregationResult.model_validate(results["aggregation"])
                if results.get("aggregation") is not None
                else None
            ),
        )
