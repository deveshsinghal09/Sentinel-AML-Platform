"""Natural-language intent and entity extraction for AML queries."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.models import IntentFilters, IntentResult
from config import GROQ_API_KEY, INTENT_MODEL


_PATTERN_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("structuring", ("structuring", "under $10,000", "under 10000", "below $10,000", "below 10000")),
    ("smurfing", ("smurfing", "smurfs")),
    ("layering", ("layering", "layered transfer", "transaction chain")),
    ("rapid_cashout", ("rapid cashout", "rapid cash-out", "cash out", "cash-out")),
    ("behavioural_change", ("behavioural change", "behavioral change", "change in behaviour", "change in behavior")),
    ("cycle", ("cycle", "circular transfer", "round trip", "round-trip")),
    ("fan_in", ("fan in", "fan-in", "many senders")),
    ("fan_out", ("fan out", "fan-out", "many recipients")),
    ("single_large", ("single large", "large transaction")),
    ("deposit_send", ("deposit-send", "deposit then send")),
    ("cash_withdrawal", ("cash withdrawal", "cash withdrawals")),
    ("bipartite", ("bipartite",)),
    ("gather_scatter", ("gather-scatter", "gather scatter")),
    ("scatter_gather", ("scatter-gather", "scatter gather")),
]

_GRAPH_PATTERNS = {
    "layering",
    "cycle",
    "bipartite",
    "gather_scatter",
    "scatter_gather",
}


class IntentExtractor:
    """Extract a validated ``IntentResult`` using Groq with a safe fallback."""

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

    def extract(self, query: str) -> IntentResult:
        """Return structured intent for a non-empty natural-language query."""
        query = query.strip()
        if not query:
            raise ValueError("query cannot be empty")

        if self._use_llm:
            try:
                result = IntentResult.model_validate(self._extract_with_llm(query))
                return self._enforce_derived_flags(result)
            except Exception as exc:
                logger.warning(
                    "Groq intent extraction failed; using deterministic fallback: {}",
                    exc,
                )

        return self._rule_based_extract(query)

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
    def _extract_with_llm(self, query: str) -> dict:
        today = date.today().isoformat()
        system_prompt = f"""
You extract intent from AML investigation queries. Today is {today}.
Return only a JSON object matching this schema:
{{
  "intent": "pattern_search" | "aggregation" | "entity_lookup" | "broad_eda",
  "pattern_type": "structuring" | "smurfing" | "layering" |
    "rapid_cashout" | "behavioural_change" | "cycle" | "fan_in" |
    "fan_out" | "single_large" | "deposit_send" | "cash_withdrawal" |
    "bipartite" | "gather_scatter" | "scatter_gather" | null,
    "filters": {{
    "date_range": ["YYYY-MM-DD", "YYYY-MM-DD"] | null,
    "entity_id": string | null,
    "from_country": string | null,
    "payment_format": string | null,
    "min_amount": number | null,
    "max_amount": number | null,
    "min_count": integer | null
  }},
  "entities": [string],
  "require_ml": boolean,
  "require_graph": boolean,
  "require_eda": boolean
}}
Use aggregation for grouped/count threshold questions such as "which customers
made 10+ transactions". Use entity_lookup only for one explicitly identified
customer or account. Do not add facts that are absent from the query.
"""
        response = self._get_client().chat.completions.create(
            model=INTENT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=700,
        )
        return json.loads(response.choices[0].message.content)

    @staticmethod
    def _enforce_derived_flags(result: IntentResult) -> IntentResult:
        update = {
            "require_eda": result.intent == "broad_eda",
            "require_ml": result.intent in {"pattern_search", "broad_eda"},
            "require_graph": result.pattern_type in _GRAPH_PATTERNS,
        }
        return result.model_copy(update=update)

    def _rule_based_extract(self, query: str) -> IntentResult:
        lower = query.lower()
        compact = re.sub(r"\s+", " ", lower)
        normalized_query = re.sub(r"\s+", " ", query)

        broad_markers = (
            "analyse this dataset",
            "analyze this dataset",
            "analyse the dataset",
            "analyze the dataset",
            "dataset overview",
            "exploratory analysis",
            "broad analysis",
            "eda",
        )
        aggregation_markers = (
            "which customers",
            "which accounts",
            "how many",
            "count of",
            "transactions under",
            "transactions below",
        )
        explicit_entity = re.search(
            r"\b(?:customer|account|entity)\b(?:\s+id)?\s*(?:#|:)?\s*"
            r"([a-z0-9][a-z0-9_-]*)\b",
            normalized_query,
            flags=re.IGNORECASE,
        )

        if any(marker in compact for marker in broad_markers):
            intent = "broad_eda"
        elif any(marker in compact for marker in aggregation_markers) or re.search(
            r"\b\d+\s*\+\s+transactions\b", compact
        ):
            intent = "aggregation"
        elif explicit_entity is not None:
            intent = "entity_lookup"
        else:
            intent = "pattern_search"

        pattern_type = None
        for candidate, aliases in _PATTERN_ALIASES:
            if any(alias in compact for alias in aliases):
                pattern_type = candidate
                break

        entity_id = explicit_entity.group(1) if explicit_entity else None
        entities = [entity_id] if entity_id else []

        date_range = self._extract_date_range(compact)
        min_amount = self._extract_amount(
            compact,
            ("over", "above", "more than", "at least"),
        )
        max_amount = self._extract_amount(
            compact,
            ("under", "below", "less than", "at most"),
        )
        min_count_match = re.search(
            r"\b(\d+)\s*(?:\+|or\s+more|or\s+above)\s+transactions?\b",
            compact,
        )
        min_count = int(min_count_match.group(1)) if min_count_match else None

        payment_format = None
        payment_aliases = {
            "ach": "ACH",
            "cheque": "Cheque",
            "check": "Cheque",
            "wire": "Wire",
            "credit card": "Credit Card",
            "debit card": "Debit Card",
            "cash deposit": "Cash Deposit",
            "cash withdrawal": "Cash Withdrawal",
        }
        for alias, canonical in payment_aliases.items():
            if re.search(rf"\b{re.escape(alias)}\b", compact):
                payment_format = canonical
                break

        country_match = re.search(
            r"\bfrom\s+(turkey|pakistan|nigeria|uae|albania|morocco|"
            r"india|uk|usa|germany|france|italy|spain)\b",
            compact,
            flags=re.IGNORECASE,
        )
        from_country = country_match.group(1).upper() if country_match else None

        result = IntentResult(
            intent=intent,
            pattern_type=pattern_type,
            filters=IntentFilters(
                date_range=date_range,
                entity_id=entity_id,
                from_country=from_country,
                payment_format=payment_format,
                min_amount=min_amount,
                max_amount=max_amount,
                min_count=min_count,
            ),
            entities=entities,
        )
        return self._enforce_derived_flags(result)

    @staticmethod
    def _extract_date_range(query: str) -> tuple[str, str] | None:
        relative = re.search(r"\blast\s+(\d{1,4})\s+days?\b", query)
        if relative:
            days = int(relative.group(1))
            end = date.today()
            start = end - timedelta(days=days)
            return start.isoformat(), end.isoformat()

        dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", query)
        if len(dates) >= 2:
            return dates[0], dates[1]
        if len(dates) == 1:
            return dates[0], dates[0]
        return None

    @staticmethod
    def _extract_amount(query: str, qualifiers: tuple[str, ...]) -> float | None:
        qualifier_pattern = "|".join(re.escape(item) for item in qualifiers)
        match = re.search(
            rf"(?:{qualifier_pattern})\s*\$?\s*([\d,]+(?:\.\d+)?)",
            query,
        )
        if not match:
            return None
        return float(match.group(1).replace(",", ""))
