from __future__ import annotations

import pandas as pd
import pytest

from tools.risk_scorer import score


def _frame(rule=0.0, stat=0.0, ml=0.0, country="USA"):
    return pd.DataFrame(
        {
            "rule_score": [rule],
            "stat_score": [stat],
            "ml_score": [ml],
            "from_country": [country],
        }
    )


def test_risk_score_in_0_1_range():
    result = score(_frame(2, -1, 0.5))
    assert result["risk_score"].between(0, 1).all()


def test_high_risk_country_adds_boost():
    normal = score(_frame(rule=0.5), ran_tools={"rule_engine"})
    nigeria = score(_frame(rule=0.5, country="Nigeria"), ran_tools={"rule_engine"})
    assert nigeria.loc[0, "risk_score"] == pytest.approx(
        normal.loc[0, "risk_score"] + 0.10
    )


@pytest.mark.parametrize(
    ("risk", "label"),
    [(0.34, "low"), (0.35, "medium"), (0.69, "medium"), (0.70, "high")],
)
def test_risk_label_boundaries(risk, label):
    result = score(_frame(rule=risk), ran_tools={"rule_engine"})
    assert result.loc[0, "risk_label"] == label


def test_normalization_when_only_rule_engine_ran():
    result = score(_frame(rule=0.8, stat=0, ml=0), ran_tools={"rule_engine"})
    assert result.loc[0, "risk_score"] == 0.8
    assert result.loc[0, "active_detector_count"] == 1


def test_normalization_when_all_three_detectors_ran():
    result = score(_frame(rule=1, stat=1, ml=1))
    assert result.loc[0, "risk_score"] == 1
    assert result.loc[0, "active_detector_count"] == 3
    contribution = result.loc[0, "risk_contribution"]
    assert (
        contribution["rule_contribution"]
        + contribution["stat_contribution"]
        + contribution["ml_contribution"]
        + contribution["country_boost"]
    ) == pytest.approx(contribution["final_risk_score"])


def test_country_boost_capped_at_1_0():
    result = score(
        _frame(rule=1, stat=1, ml=1, country="Nigeria"),
        ran_tools={"rule_engine", "statistical", "ml_engine"},
    )
    assert result.loc[0, "risk_score"] == 1
