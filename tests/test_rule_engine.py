from __future__ import annotations

import pandas as pd

from tools.feature_engineering import engineer_features
from tools.rule_engine import run_rules


def _featured(frame: pd.DataFrame) -> pd.DataFrame:
    return engineer_features(frame)


def test_structuring_rule_fires_on_valid_pattern(sample_transactions):
    result = run_rules(_featured(sample_transactions), ["structuring"])
    assert "structuring" in result.loc[2, "rule_flags"]


def test_structuring_rule_does_not_fire_below_count(sample_transactions):
    result = run_rules(_featured(sample_transactions.iloc[:2]), ["structuring"])
    assert not result["rule_flags"].map(lambda flags: "structuring" in flags).any()


def test_smurfing_rule_fires_on_fan_in_pattern(sample_transactions):
    result = run_rules(_featured(sample_transactions), ["smurfing"])
    assert "smurfing" in result.loc[5, "rule_flags"]


def test_high_risk_country_flag_fires_for_nigeria(sample_transactions):
    result = run_rules(_featured(sample_transactions))
    assert "high_risk_country" in result.loc[5, "rule_flags"]


def test_rule_score_is_fraction_of_rules_fired(sample_transactions):
    result = run_rules(_featured(sample_transactions), ["structuring"])
    assert result.loc[2, "rule_score"] == 0.5


def test_pattern_type_filter_restricts_rules(sample_transactions):
    result = run_rules(_featured(sample_transactions), ["structuring"])
    assert all(
        set(flags).issubset({"structuring", "high_risk_country"})
        for flags in result["rule_flags"]
    )


def test_no_double_counting_of_same_rule(sample_transactions):
    result = run_rules(_featured(sample_transactions), ["smurfing", "smurfing"])
    assert all(len(flags) == len(set(flags)) for flags in result["rule_flags"])


def test_run_rules_preserves_row_count(sample_transactions):
    assert len(run_rules(_featured(sample_transactions))) == len(sample_transactions)
