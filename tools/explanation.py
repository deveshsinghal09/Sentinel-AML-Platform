"""Grounded entity explanations and SAR-draft generation."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from config import (
    EXPLANATION_MODEL,
    FALLBACK_MODEL,
    GROQ_API_KEY,
)


_KB_PATH = (
    Path(__file__).resolve().parent.parent
    / "knowledge_base"
    / "typologies.json"
)

_PATTERN_ALIASES = {
    "layering": "layered_fan_in",
    "rapid_cashout": "cash_withdrawal",
    "behavioural_change": "behavioural_change_1",
}

_FLAG_TO_TYPOLOGY = {
    "structuring": "structuring",
    "smurfing": "smurfing",
    "rapid_cashout": "cash_withdrawal",
    "single_large": "single_large",
    "deposit_send": "deposit_send",
    "fan_in": "fan_in",
    "fan_out": "fan_out",
}

_FEATURE_FIELDS = [
    "timestamp",
    "from_account",
    "to_account",
    "amount_paid",
    "payment_format",
    "txn_count_7d",
    "rolling_sum_7d",
    "near_threshold_count",
    "amount_deviation",
    "velocity_1hr",
    "fan_in_count",
    "cross_border_flag",
    "z_score",
    "iqr_flag",
    "iso_score",
    "anomaly_label",
    "rule_flags",
    "rule_score",
    "stat_score",
    "ml_score",
    "country_risk_boost",
    "risk_score",
    "risk_label",
    "escalation_action",
]

_NUMBER_RE = re.compile(
    r"(?<![\w])\$?-?\d[\d,]*(?:\.\d+)?(?![\w])"
)


@lru_cache(maxsize=1)
def _typology_catalogue() -> dict[str, dict]:
    with _KB_PATH.open(encoding="utf-8") as source:
        return json.load(source)


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _feature_payload(row: pd.Series) -> dict[str, Any]:
    payload = {
        field: _json_value(row[field])
        for field in _FEATURE_FIELDS
        if field in row.index
    }
    payload["entity_id"] = str(row.get("from_account", ""))
    return payload


def _numbers_from_value(value: Any) -> list[float]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float, np.integer, np.floating)):
        return [float(value)]
    if isinstance(value, dict):
        return [
            number
            for nested in value.values()
            for number in _numbers_from_value(nested)
        ]
    if isinstance(value, (list, tuple, set)):
        return [
            number
            for nested in value
            for number in _numbers_from_value(nested)
        ]
    if isinstance(value, str):
        numbers = []
        for token in _NUMBER_RE.findall(value):
            try:
                numbers.append(float(token.replace("$", "").replace(",", "")))
            except ValueError:
                continue
        return numbers
    return []


def numbers_are_grounded(text: str, feature_json: dict[str, Any]) -> bool:
    """Return true when every standalone output number exists in features."""
    allowed = _numbers_from_value(feature_json)
    for token in _NUMBER_RE.findall(text):
        candidate = float(token.replace("$", "").replace(",", ""))
        if not any(
            abs(candidate - value)
            <= max(0.001, abs(value) * 0.0001)
            for value in allowed
        ):
            return False
    return True


def _resolve_typology(
    row: pd.Series,
    intent_result: dict,
) -> dict[str, Any]:
    catalogue = _typology_catalogue()
    flags = row.get("rule_flags", [])
    key = None
    if isinstance(flags, (list, tuple, set)):
        for flag in flags:
            if flag in _FLAG_TO_TYPOLOGY:
                key = _FLAG_TO_TYPOLOGY[flag]
                break
    if key is None:
        pattern = intent_result.get("pattern_type")
        key = _PATTERN_ALIASES.get(pattern, pattern)
    if key is None:
        if bool(row.get("iqr_flag", False)):
            key = "behavioural_change_2"
        elif float(row.get("stat_score", 0) or 0) > 0:
            key = "behavioural_change_1"
        elif float(row.get("ml_score", 0) or 0) > 0:
            key = "gather_scatter"
    typology = catalogue.get(key or "", {})
    return {
        "key": key or "",
        "name": typology.get("name", "Unclassified AML anomaly"),
        "saml_d_label": typology.get("saml_d_label", ""),
        "reg_ref": typology.get(
            "reg_ref",
            "Internal AML monitoring policy",
        ),
        "description": typology.get("description", ""),
    }


def _select_knowledge(
    typology: dict[str, Any],
    snippets: list[dict],
) -> dict:
    for snippet in snippets:
        if (
            snippet.get("id") == typology["key"]
            or snippet.get("typology_id") == typology["key"]
            or snippet.get("saml_d_label") == typology["saml_d_label"]
        ):
            return snippet

    if typology["saml_d_label"]:
        from agent.knowledge import get_knowledge

        matches = get_knowledge().lookup(typology["saml_d_label"], top_k=1)
        if matches:
            return matches[0]
    return snippets[0] if snippets else {}


def _fallback_output(
    features: dict[str, Any],
    typology: dict[str, Any],
) -> dict[str, str]:
    entity = str(features.get("entity_id", ""))
    risk = float(features.get("risk_score") or 0.0)
    flags = features.get("rule_flags") or []
    flag_text = ", ".join(str(flag) for flag in flags) if flags else "none"
    label = typology["saml_d_label"] or "Unclassified_AML_Anomaly"
    return {
        "explanation": (
            f"Entity {entity} received a composite risk score of "
            f"{risk:.4f} from the detectors that ran. Observed rule signals "
            f"were {flag_text}; the closest grounded SAML-D typology is "
            f"{label}."
        ),
        "sar_draft": (
            f"Review entity {entity} for activity consistent with {label}; "
            f"the observed composite risk score is {risk:.4f}."
        ),
        "citation": typology["reg_ref"],
    }


class ExplanationGenerator:
    """Generate and validate one grounded explanation at a time."""

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

    def _get_client(self) -> Any:
        if self._client is None:
            if not GROQ_API_KEY:
                raise RuntimeError("GROQ_API_KEY is not configured")
            from groq import Groq

            self._client = Groq(api_key=GROQ_API_KEY)
        return self._client

    def _call_model(
        self,
        model: str,
        features: dict[str, Any],
        typology: dict[str, Any],
        knowledge: dict,
        correction: bool = False,
    ) -> dict:
        excerpt = str(knowledge.get("text", typology["description"]))
        correction_text = (
            "\nYour previous output included a number absent from Feature "
            "values. Regenerate without any unsupported number."
            if correction
            else ""
        )
        prompt = f"""
Generate a 2-3 sentence explanation for why this entity was flagged.
Only reference the feature values and knowledge excerpt provided.
Do not invent numbers. End with a separate one-line SAR draft sentence.

Feature values: {json.dumps(features, default=str)}
Detected typology (SAML-D label): {typology["saml_d_label"]}
Typology name: {typology["name"]} ({typology["reg_ref"]})
Knowledge base excerpt: {excerpt}

Return JSON:
{{"explanation": "...", "sar_draft": "...", "citation": "..."}}
{correction_text}
"""
        response = self._get_client().chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write evidence-grounded AML explanations and "
                        "never add facts not present in the input."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=600,
        )
        return json.loads(response.choices[0].message.content)

    def generate(
        self,
        features: dict[str, Any],
        typology: dict[str, Any],
        knowledge: dict,
    ) -> dict[str, str]:
        if not self._use_llm:
            return _fallback_output(features, typology)

        output = None
        used_model = EXPLANATION_MODEL
        try:
            output = self._call_model(
                EXPLANATION_MODEL,
                features,
                typology,
                knowledge,
            )
        except Exception as exc:
            logger.warning(
                "Primary explanation model failed; trying fallback {}: {}",
                FALLBACK_MODEL,
                exc,
            )
            used_model = FALLBACK_MODEL
            try:
                output = self._call_model(
                    FALLBACK_MODEL,
                    features,
                    typology,
                    knowledge,
                )
            except Exception as fallback_exc:
                logger.warning(
                    "Fallback explanation model failed; using template: {}",
                    fallback_exc,
                )
                return _fallback_output(features, typology)

        combined = (
            f"{output.get('explanation', '')} "
            f"{output.get('sar_draft', '')}"
        )
        has_required_text = bool(
            str(output.get("explanation", "")).strip()
            and str(output.get("sar_draft", "")).strip()
        )
        if not has_required_text or not numbers_are_grounded(
            combined,
            features,
        ):
            logger.warning(
                "Explanation numeric validator rejected output; regenerating"
            )
            try:
                output = self._call_model(
                    used_model,
                    features,
                    typology,
                    knowledge,
                    correction=True,
                )
            except Exception:
                return _fallback_output(features, typology)
            combined = (
                f"{output.get('explanation', '')} "
                f"{output.get('sar_draft', '')}"
            )
            has_required_text = bool(
                str(output.get("explanation", "")).strip()
                and str(output.get("sar_draft", "")).strip()
            )
            if not has_required_text or not numbers_are_grounded(
                combined,
                features,
            ):
                logger.warning(
                    "Regenerated explanation remained ungrounded; "
                    "using deterministic template"
                )
                return _fallback_output(features, typology)

        return {
            "explanation": str(output.get("explanation", "")),
            "sar_draft": str(output.get("sar_draft", "")),
            # Citation is source-controlled rather than model-controlled.
            "citation": typology["reg_ref"],
        }


def explain(
    df: pd.DataFrame,
    intent_result: dict,
    knowledge_snippets: list[dict] | None = None,
    max_entities: int = 20,
    generator: ExplanationGenerator | None = None,
) -> pd.DataFrame:
    """Add grounded explanation fields for highest-risk unique entities."""
    if max_entities <= 0:
        raise ValueError("max_entities must be greater than zero")

    result = df.copy()
    result["saml_d_typology"] = ""
    result["explanation"] = ""
    result["sar_draft"] = ""
    result["citation"] = ""
    if result.empty or "risk_score" not in result:
        return result

    candidates = result.loc[
        pd.to_numeric(result["risk_score"], errors="coerce").fillna(0) >= 0.35
    ].copy()
    if candidates.empty:
        return result

    candidates = candidates.sort_values(
        "risk_score",
        ascending=False,
        kind="stable",
    )
    if "from_account" in candidates:
        candidates = candidates.drop_duplicates("from_account")
    candidates = candidates.head(max_entities)

    snippets = knowledge_snippets or []
    engine = generator or ExplanationGenerator()
    knowledge_cache: dict[str, dict] = {}
    for index, row in candidates.iterrows():
        typology = _resolve_typology(row, intent_result)
        label = typology["saml_d_label"]
        if label not in knowledge_cache:
            knowledge_cache[label] = _select_knowledge(typology, snippets)
        features = _feature_payload(row)
        generated = engine.generate(
            features,
            typology,
            knowledge_cache[label],
        )
        result.at[index, "saml_d_typology"] = label
        result.at[index, "explanation"] = generated["explanation"]
        result.at[index, "sar_draft"] = generated["sar_draft"]
        result.at[index, "citation"] = generated["citation"]
    return result
