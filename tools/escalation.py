"""Map composite risk scores to operational escalation actions."""
from __future__ import annotations

import numpy as np
import pandas as pd


MONITOR_MAX_SCORE = 0.40
REVIEW_MAX_SCORE = 0.70


def get_action(risk_score: float) -> str:
    """Return the configured action for one normalized risk score."""
    if pd.isna(risk_score) or risk_score < MONITOR_MAX_SCORE:
        return "monitor"
    if risk_score < REVIEW_MAX_SCORE:
        return "flag_for_review"
    return "report"


def recommend(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``escalation_action`` with an explicit PEP-report override."""
    result = df.copy()
    risk = (
        pd.to_numeric(
            result.get("risk_score", pd.Series(0.0, index=result.index)),
            errors="coerce",
        )
        .fillna(0.0)
        .clip(0.0, 1.0)
    )
    actions = np.select(
        [risk.lt(MONITOR_MAX_SCORE), risk.lt(REVIEW_MAX_SCORE)],
        ["monitor", "flag_for_review"],
        default="report",
    )

    if "rule_flags" in result:
        pep_mask = result["rule_flags"].map(
            lambda flags: (
                isinstance(flags, (list, tuple, set))
                and bool({"pep", "pep_involvement"}.intersection(flags))
            )
        ).to_numpy(dtype=bool)
        actions[pep_mask] = "report"

    result["escalation_action"] = actions
    return result
