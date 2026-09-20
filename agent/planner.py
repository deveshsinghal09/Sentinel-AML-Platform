"""Policy-constrained dynamic tool planner."""
from __future__ import annotations

import json
from typing import Any

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.models import IntentResult, PlanResult, SkippedTool
from agent.validator import ALLOWED_TOOLS, validate_plan
from config import GROQ_API_KEY, INTENT_MODEL


TOOL_ORDER = [
    "data_loader",
    "aggregation",
    "eda",
    "feature_engineering",
    "rule_engine",
    "statistical",
    "ml_engine",
    "graph_tool",
    "risk_scorer",
    "escalation",
    "explanation",
]

_RULE_PATTERNS = {
    "structuring",
    "smurfing",
    "fan_in",
    "fan_out",
    "single_large",
    "deposit_send",
    "cash_withdrawal",
    "rapid_cashout",
}


class DynamicPlanner:
    """Build the minimal allowed tool plan for a validated intent."""

    def __init__(
        self,
        client: Any | None = None,
        use_llm: bool | None = None,
    ) -> None:
        self._client = client
        self._use_llm = (
            bool(client) or bool(GROQ_API_KEY)
            if use_llm is None
            else use_llm
        )

    def plan(
        self,
        intent_result: IntentResult | dict,
        knowledge_context: list[dict] | None = None,
    ) -> PlanResult:
        """Return a validated, ordered, policy-minimal plan."""
        intent = IntentResult.model_validate(intent_result)
        required = self._policy_steps(intent)
        reasoning = self._policy_reasoning(intent)

        if self._use_llm:
            try:
                proposal = self._plan_with_llm(
                    intent,
                    knowledge_context or [],
                )
                proposed_steps = validate_plan(proposal.get("steps", []))
                if proposed_steps != required:
                    logger.info(
                        "Planner policy normalized LLM steps {} to {}",
                        proposed_steps,
                        required,
                    )
                llm_reasoning = str(proposal.get("reasoning", "")).strip()
                if llm_reasoning:
                    reasoning = llm_reasoning
            except Exception as exc:
                logger.warning(
                    "Groq planning failed; using deterministic policy plan: {}",
                    exc,
                )

        selected = set(required)
        skipped = [
            SkippedTool(
                tool=tool,
                reason=self._skip_reason(tool, intent),
            )
            for tool in TOOL_ORDER
            if tool not in selected
        ]
        return PlanResult(
            steps=required,
            skipped=skipped,
            reasoning=reasoning,
        )

    @staticmethod
    def _policy_steps(intent: IntentResult) -> list[str]:
        selected = {"data_loader", "risk_scorer", "escalation", "explanation"}

        if intent.intent == "broad_eda":
            selected.update(
                {"eda", "feature_engineering", "statistical", "ml_engine"}
            )
        elif intent.intent == "pattern_search":
            selected.update(
                {"feature_engineering", "statistical", "ml_engine"}
            )
        elif intent.intent == "entity_lookup":
            selected.update(
                {"feature_engineering", "rule_engine", "statistical"}
            )
        elif intent.intent == "aggregation":
            selected.add("aggregation")

        if (
            intent.intent != "aggregation"
            and intent.pattern_type in _RULE_PATTERNS
        ):
            selected.add("rule_engine")
        if intent.require_ml:
            selected.add("ml_engine")
        if intent.require_graph:
            selected.add("graph_tool")
        if intent.require_eda:
            selected.add("eda")

        return [tool for tool in TOOL_ORDER if tool in selected]

    @staticmethod
    def _policy_reasoning(intent: IntentResult) -> str:
        pattern = intent.pattern_type or "no specific typology"
        return (
            f"Selected the minimal {intent.intent} workflow for {pattern}; "
            "risk scoring, escalation, and explanation remain mandatory."
        )

    @staticmethod
    def _skip_reason(tool: str, intent: IntentResult) -> str:
        if tool == "eda":
            return f"intent is {intent.intent}, not broad_eda"
        if tool == "aggregation":
            return f"intent is {intent.intent}, not aggregation"
        if tool == "feature_engineering":
            return f"intent {intent.intent} does not require derived AML features"
        if tool == "rule_engine":
            return (
                f"pattern {intent.pattern_type or 'unspecified'} has no "
                "Phase 2 rule-selection requirement"
            )
        if tool == "statistical":
            return f"intent {intent.intent} does not require statistical scoring"
        if tool == "ml_engine":
            return "require_ml is false"
        if tool == "graph_tool":
            return (
                f"pattern {intent.pattern_type or 'unspecified'} does not "
                "require graph analysis"
            )
        return "tool is not required by the selected minimal workflow"

    def _get_client(self) -> Any:
        if self._client is None:
            if not GROQ_API_KEY:
                raise RuntimeError("GROQ_API_KEY is not configured")
            from groq import Groq

            self._client = Groq(api_key=GROQ_API_KEY)
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def _plan_with_llm(
        self,
        intent: IntentResult,
        knowledge_context: list[dict],
    ) -> dict:
        prompt = f"""
Create the smallest ordered AML tool plan. Return JSON with keys steps,
skipped, and reasoning. Allowed tools are: {sorted(ALLOWED_TOOLS)}.

Mandatory rules:
- data_loader is always first.
- eda only runs for broad_eda.
- feature_engineering and statistical run for pattern_search/entity_lookup.
- broad_eda also runs feature_engineering, statistical, and ml_engine.
- aggregation runs only for direct grouped/count threshold questions.
- rule_engine runs for rule-compatible patterns or entity_lookup.
- ml_engine runs only when require_ml is true.
- graph_tool runs only when require_graph is true.
- risk_scorer, escalation, explanation are always the final three tools.

Intent:
{intent.model_dump_json()}

Knowledge context:
{json.dumps(knowledge_context[:3], default=str)}
"""
        response = self._get_client().chat.completions.create(
            model=INTENT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a policy-constrained AML tool planner.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=900,
        )
        return json.loads(response.choices[0].message.content)
