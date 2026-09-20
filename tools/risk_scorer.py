"""Composite risk scoring normalized over the detectors that actually ran."""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from config import RISK_HIGH_THRESHOLD, RISK_LOW_THRESHOLD


BASE_WEIGHTS = {
    "rule_engine": 0.40,
    "statistical": 0.25,
    "ml_engine": 0.35,
}

_SCORE_COLUMNS = {
    "rule_engine": "rule_score",
    "statistical": "stat_score",
    "ml_engine": "ml_score",
}

HIGH_RISK_COUNTRY_BOOST = 0.10
HIGH_RISK_COUNTRIES = {
    "turkey",
    "pakistan",
    "nigeria",
    "uae",
    "albania",
    "morocco",
}


def _country_risk_mask(df: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=df.index)
    for column in ("from_country", "to_country"):
        if column in df:
            values = (
                df[column].astype("string").fillna("").str.strip().str.lower()
            )
            mask |= values.isin(HIGH_RISK_COUNTRIES)
    if "rule_flags" in df:
        mask |= df["rule_flags"].map(
            lambda flags: (
                isinstance(flags, (list, tuple, set))
                and "high_risk_country" in flags
            )
        )
    return mask


def _active_detectors(
    df: pd.DataFrame,
    ran_tools: Iterable[str] | None,
) -> list[str]:
    ran = set(ran_tools) if ran_tools is not None else set(BASE_WEIGHTS)
    return [
        detector
        for detector in BASE_WEIGHTS
        if detector in ran and _SCORE_COLUMNS[detector] in df
    ]


def score(
    df: pd.DataFrame,
    ran_tools: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Add normalized ``risk_score`` and low/medium/high ``risk_label``.

    A missing/skipped detector contributes neither a zero nor its weight. This
    prevents a narrow rule-only plan from being artificially diluted.
    """
    result = df.copy()
    active = _active_detectors(result, ran_tools)
    risk = np.zeros(len(result), dtype=float)
    contributions = {
        detector: np.zeros(len(result), dtype=float)
        for detector in BASE_WEIGHTS
    }
    score_values = {
        detector: np.zeros(len(result), dtype=float)
        for detector in BASE_WEIGHTS
    }
    active_weight = sum(BASE_WEIGHTS[detector] for detector in active)

    if active:
        for detector in active:
            values = (
                pd.to_numeric(
                    result[_SCORE_COLUMNS[detector]],
                    errors="coerce",
                )
                .fillna(0.0)
                .clip(0.0, 1.0)
                .to_numpy(dtype=float)
            )
            detector_contribution = (
                values * BASE_WEIGHTS[detector] / active_weight
            )
            score_values[detector] = values
            contributions[detector] = detector_contribution
            risk += detector_contribution

    country_mask = _country_risk_mask(result).to_numpy(dtype=bool)
    country_boost = country_mask.astype(float) * HIGH_RISK_COUNTRY_BOOST
    risk = np.round(
        np.clip(risk + country_boost, 0.0, 1.0),
        12,
    )

    labels = np.select(
        [
            risk < RISK_LOW_THRESHOLD,
            risk < RISK_HIGH_THRESHOLD,
        ],
        ["low", "medium"],
        default="high",
    )
    result["country_risk_boost"] = country_boost
    result["active_detector_count"] = len(active)
    result["risk_score"] = risk
    result["risk_label"] = labels
    formula_parts = [
        (
            f"{BASE_WEIGHTS[detector]:.2f}/{active_weight:.2f}"
            f"*{_SCORE_COLUMNS[detector]}"
        )
        for detector in active
    ]
    formula = " + ".join(formula_parts) if formula_parts else "no detectors"
    formula += " + country_boost"
    result["risk_contribution"] = [
        {
            "rule_score": float(score_values["rule_engine"][index]),
            "rule_weight": BASE_WEIGHTS["rule_engine"],
            "rule_contribution": float(
                contributions["rule_engine"][index]
            ),
            "stat_score": float(score_values["statistical"][index]),
            "stat_weight": BASE_WEIGHTS["statistical"],
            "stat_contribution": float(
                contributions["statistical"][index]
            ),
            "ml_score": float(score_values["ml_engine"][index]),
            "ml_weight": BASE_WEIGHTS["ml_engine"],
            "ml_contribution": float(contributions["ml_engine"][index]),
            "country_boost": float(country_boost[index]),
            "active_detector_count": len(active),
            "final_risk_score": float(risk[index]),
            "formula": formula,
        }
        for index in range(len(result))
    ]
    return result
