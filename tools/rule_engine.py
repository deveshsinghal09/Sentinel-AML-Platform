"""Calibrated, explainable AML rules and SAML-D validation helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger


STRUCTURING_THRESHOLD = 10_000.0
STRUCTURING_LOWER_BOUND = 8_000.0
STRUCTURING_MIN_COUNT = 3
STRUCTURING_WINDOW_DAYS = 7

SMURFING_MIN_SENDERS = 3
SMURFING_WINDOW_HOURS = 48
SMURFING_TOTAL_THRESH = 10_000.0

CASHOUT_WINDOW_HOURS = 24

HIGH_RISK_COUNTRIES = {
    "turkey",
    "pakistan",
    "nigeria",
    "uae",
    "albania",
    "morocco",
}

_RULE_ORDER = [
    "structuring",
    "smurfing",
    "rapid_cashout",
    "single_large",
    "deposit_send",
    "fan_in",
    "fan_out",
    "high_risk_country",
]

_PATTERN_TO_RULE = {
    "structuring": "structuring",
    "smurfing": "smurfing",
    "rapid_cashout": "rapid_cashout",
    "cash_withdrawal": "rapid_cashout",
    "single_large": "single_large",
    "deposit_send": "deposit_send",
    "fan_in": "fan_in",
    "fan_out": "fan_out",
}


def _numeric(
    df: pd.DataFrame,
    column: str,
    default: float = 0.0,
) -> pd.Series:
    if column not in df:
        return pd.Series(default, index=df.index, dtype=float)
    return pd.to_numeric(df[column], errors="coerce").fillna(default)


def _country_risk_mask(df: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=df.index)
    for column in ("from_country", "to_country"):
        if column in df:
            countries = (
                df[column].astype("string").fillna("").str.strip().str.lower()
            )
            mask |= countries.isin(HIGH_RISK_COUNTRIES)
    return mask


def _selected_rules(
    pattern_types: list[str] | None,
    has_country: bool,
) -> list[str]:
    if pattern_types:
        selected = {
            _PATTERN_TO_RULE[pattern]
            for pattern in pattern_types
            if pattern in _PATTERN_TO_RULE
        }
    else:
        selected = set(_RULE_ORDER[:-1])
    if has_country:
        selected.add("high_risk_country")
    return [rule for rule in _RULE_ORDER if rule in selected]


def run_rules(
    df: pd.DataFrame,
    pattern_types: list[str] | None = None,
) -> pd.DataFrame:
    """Apply selected AML rules and add ``rule_flags`` / ``rule_score``.

    Feature engineering must run first. Missing derived columns are treated as
    neutral rather than guessed.
    """
    result = df.copy()
    amount = _numeric(result, "amount_paid")
    near_count = _numeric(result, "near_threshold_count")
    fan_in_count = _numeric(result, "fan_in_count")
    fan_in_sum = _numeric(result, "fan_in_sum_48h")
    fan_out_count = _numeric(result, "fan_out_count")
    velocity = _numeric(result, "velocity_1hr")
    recent_inflow = _numeric(result, "recent_inflow_24h")
    txn_count = _numeric(result, "txn_count_7d")
    rolling_sum = _numeric(result, "rolling_sum_7d")
    payment_format = (
        result.get(
            "payment_format",
            pd.Series("", index=result.index),
        )
        .astype("string")
        .fillna("")
        .str.strip()
        .str.lower()
    )

    masks = {
        "structuring": (
            amount.ge(STRUCTURING_LOWER_BOUND)
            & amount.lt(STRUCTURING_THRESHOLD)
            & near_count.ge(STRUCTURING_MIN_COUNT)
        ),
        "smurfing": (
            (
                fan_in_count.ge(SMURFING_MIN_SENDERS)
                & fan_in_sum.ge(SMURFING_TOTAL_THRESH)
            )
            |
            (
                payment_format.eq("cash deposit")
                & txn_count.ge(STRUCTURING_MIN_COUNT)
                & rolling_sum.ge(SMURFING_TOTAL_THRESH)
            )
        ),
        "rapid_cashout": (
            payment_format.isin({"cash withdrawal", "cash"})
            & (
                recent_inflow.gt(0)
                | txn_count.ge(STRUCTURING_MIN_COUNT)
            )
        ),
        "single_large": amount.ge(STRUCTURING_THRESHOLD),
        "deposit_send": recent_inflow.gt(0),
        "fan_in": fan_in_count.ge(SMURFING_MIN_SENDERS),
        "fan_out": fan_out_count.ge(3),
        "high_risk_country": _country_risk_mask(result),
    }

    applicable = _selected_rules(
        pattern_types,
        has_country=(
            "from_country" in result.columns
            or "to_country" in result.columns
        ),
    )
    flags = [[] for _ in range(len(result))]
    fired_count = np.zeros(len(result), dtype=float)
    for rule in applicable:
        fired_positions = np.flatnonzero(masks[rule].to_numpy(dtype=bool))
        for position in fired_positions:
            flags[position].append(rule)
            fired_count[position] += 1

    result["rule_flags"] = flags
    denominator = max(len(applicable), 1)
    result["rule_score"] = np.clip(fired_count / denominator, 0.0, 1.0)
    return result


def validate_rules_against_saml(
    conn=None,
) -> dict[str, dict[str, float | int | str]]:
    """Measure rule recall on matching SAML-D positive labels.

    This diagnostic never modifies thresholds and never joins SAML-D to
    HI-Small. Low recall is reported as-is.
    """
    from tools.data_loader import get_db_connection
    from tools.feature_engineering import engineer_features

    own_conn = conn is None
    db = conn or get_db_connection()
    try:
        positives = db.execute(
            """
            SELECT
                timestamp,
                from_account,
                to_account,
                amount AS amount_paid,
                payment_format,
                from_country,
                to_country,
                laundering_type
            FROM saml_knowledge
            WHERE is_laundering = 1
            ORDER BY timestamp
            """
        ).df()
    finally:
        if own_conn:
            db.close()

    features = engineer_features(positives)
    label_rules = {
        "Structuring": ("structuring", "structuring"),
        "Smurfing": ("smurfing", "smurfing"),
        "Cash_Withdrawal": ("cash_withdrawal", "rapid_cashout"),
        "Single_large": ("single_large", "single_large"),
        "Deposit-Send": ("deposit_send", "deposit_send"),
        "Fan_In": ("fan_in", "fan_in"),
        "Fan_Out": ("fan_out", "fan_out"),
    }

    metrics: dict[str, dict[str, float | int | str]] = {}
    for label, (pattern, flag_name) in label_rules.items():
        subset_mask = features["laundering_type"].eq(label)
        total = int(subset_mask.sum())
        scored = run_rules(features, pattern_types=[pattern])
        fired = int(
            scored.loc[subset_mask, "rule_flags"].map(
                lambda flags: flag_name in flags
            ).sum()
        )
        recall = fired / total if total else 0.0
        metrics[label] = {
            "total": total,
            "flagged": fired,
            "recall": round(recall, 4),
        }
        if label == "Structuring" and fired == 0:
            metrics[label]["note"] = (
                "The compact SAML-D table retains all positive rows but only "
                "a random normal sample; no Structuring source account has "
                "three retained transactions, so the sequence rule cannot "
                "be reconstructed without weakening its minimum-count policy."
            )
        logger.info(
            "SAML-D rule validation {}: {}/{} recall={:.2%}",
            label,
            fired,
            total,
            recall,
        )
    return metrics
