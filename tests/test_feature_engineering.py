from __future__ import annotations

import pandas as pd
import pytest

from tools.feature_engineering import (
    FEATURE_COLUMNS,
    compute_feature_family,
    engineer_features,
    selected_feature_families,
)


def test_output_has_all_aml_columns(sample_transactions):
    result = engineer_features(sample_transactions)
    assert set(FEATURE_COLUMNS).issubset(result.columns)
    assert "fan_in_sum_48h" in result.columns


def test_near_threshold_count_correct(sample_transactions):
    result = engineer_features(sample_transactions)
    assert result.loc[2, "near_threshold_count"] == 3


def test_fan_in_count_aggregates_distinct_senders(sample_transactions):
    result = engineer_features(sample_transactions)
    assert result.loc[5, "fan_in_count"] == 3


def test_empty_dataframe_returns_empty_with_columns():
    empty = pd.DataFrame(
        columns=["timestamp", "from_account", "to_account", "amount_paid"]
    )
    result = engineer_features(empty)
    assert result.empty
    assert set(FEATURE_COLUMNS).issubset(result.columns)


def test_missing_timestamp_is_rejected_cleanly():
    frame = pd.DataFrame(
        {"from_account": ["A"], "to_account": ["B"], "amount_paid": [1.0]}
    )
    with pytest.raises(ValueError, match="timestamp"):
        engineer_features(frame)


def test_structuring_family_is_genuinely_selective(sample_transactions):
    result = compute_feature_family(
        sample_transactions,
        "structuring_features",
    )
    assert {
        "txn_count_7d",
        "rolling_sum_7d",
        "near_threshold_count",
    }.issubset(result.columns)
    assert "fan_out_count" not in result
    assert "recent_inflow_24h" not in result
    assert "amount_deviation" not in result


def test_ml_contract_adds_only_model_required_families():
    families = selected_feature_families(
        ["structuring"],
        require_model_features=True,
    )
    assert families == [
        "structuring_features",
        "velocity_features",
        "behavioral_features",
    ]
