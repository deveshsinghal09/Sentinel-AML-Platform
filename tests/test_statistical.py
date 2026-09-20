from __future__ import annotations

import pandas as pd

from tools.statistical import run_statistical


def test_z_score_above_threshold_sets_stat_score_1():
    frame = pd.DataFrame(
        {
            "from_account": ["A"] * 20,
            "amount_paid": [0.0] * 19 + [100.0],
        }
    )
    result = run_statistical(frame, iqr_bounds=(-1_000, 1_000))
    assert abs(result.iloc[-1]["z_score"]) > 3
    assert result.iloc[-1]["stat_score"] == 1


def test_z_score_below_threshold_stays_below_one():
    frame = pd.DataFrame(
        {"from_account": ["A", "A", "A"], "amount_paid": [9.0, 10.0, 11.0]}
    )
    result = run_statistical(frame, iqr_bounds=(-1_000, 1_000))
    assert result["stat_score"].max() < 1


def test_iqr_outlier_flagged():
    frame = pd.DataFrame({"from_account": ["A"], "amount_paid": [101.0]})
    result = run_statistical(frame, iqr_bounds=(0.0, 100.0))
    assert bool(result.loc[0, "iqr_flag"])
    assert result.loc[0, "stat_score"] == 1


def test_stat_score_column_in_range_0_to_1():
    frame = pd.DataFrame(
        {"from_account": ["A", "A", "B"], "amount_paid": [1.0, 100.0, 5.0]}
    )
    result = run_statistical(frame, iqr_bounds=(0.0, 50.0))
    assert result["stat_score"].between(0, 1).all()


def test_empty_df_returns_empty_with_columns():
    frame = pd.DataFrame(columns=["from_account", "amount_paid"])
    result = run_statistical(frame, iqr_bounds=(0.0, 1.0))
    assert result.empty
    assert {"z_score", "iqr_flag", "stat_score"}.issubset(result.columns)
