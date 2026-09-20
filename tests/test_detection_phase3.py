"""Phase 3 feature, rule, statistical, and ML tests."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.feature_engineering import FEATURE_COLUMNS, engineer_features
from tools.ml_engine import (
    FEATURES,
    get_model_bundle,
    run_ml,
    train_isolation_forest,
)
from tools.rule_engine import run_rules
from tools.statistical import get_saml_iqr_bounds, run_statistical


def synthetic_transactions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # Structuring sequence.
            ("2022-01-01 09:00", "A", "X", 9000, "ACH", "UK", "UK"),
            ("2022-01-02 09:00", "A", "Y", 9100, "ACH", "UK", "UK"),
            ("2022-01-03 09:00", "A", "W", 9200, "ACH", "UK", "UK"),
            # Fan-in / smurfing sequence.
            ("2022-01-04 09:00", "B", "Z", 4000, "ACH", "UK", "UK"),
            ("2022-01-04 10:00", "C", "Z", 4000, "ACH", "UK", "UK"),
            ("2022-01-04 11:00", "D", "Z", 4000, "ACH", "UK", "UK"),
            # Receive then cash out.
            ("2022-01-05 09:00", "P", "CASHER", 5000, "ACH", "UK", "UK"),
            (
                "2022-01-05 10:00",
                "CASHER",
                "Q",
                4900,
                "Cash Withdrawal",
                "UK",
                "UK",
            ),
            # Country-risk signal.
            (
                "2022-01-06 09:00",
                "RISKY",
                "Q2",
                100,
                "ACH",
                "Turkey",
                "UK",
            ),
        ],
        columns=[
            "timestamp",
            "from_account",
            "to_account",
            "amount_paid",
            "payment_format",
            "from_country",
            "to_country",
        ],
    )


def test_feature_engineering_computes_required_columns_and_windows():
    featured = engineer_features(synthetic_transactions())
    assert set(FEATURE_COLUMNS).issubset(featured.columns)

    structuring_row = featured.iloc[2]
    assert structuring_row["txn_count_7d"] == 3
    assert structuring_row["near_threshold_count"] == 3
    assert structuring_row["rolling_sum_7d"] == 27_300
    assert structuring_row["fan_out_count"] == 3

    smurfing_row = featured.iloc[5]
    assert smurfing_row["fan_in_count"] == 3
    assert smurfing_row["fan_in_sum_48h"] == 12_000

    cashout_row = featured.iloc[7]
    assert cashout_row["recent_inflow_24h"] >= 5_000

    assert featured.iloc[8]["cross_border_flag"] == 1


def test_rule_engine_flags_structuring_smurfing_and_cashout():
    featured = engineer_features(synthetic_transactions())

    structuring = run_rules(featured, ["structuring"])
    assert "structuring" in structuring.iloc[2]["rule_flags"]
    assert structuring.iloc[2]["rule_score"] > 0
    assert "structuring" not in structuring.iloc[0]["rule_flags"]

    smurfing = run_rules(featured, ["smurfing"])
    assert "smurfing" in smurfing.iloc[5]["rule_flags"]

    cashout = run_rules(featured, ["cash_withdrawal"])
    assert "rapid_cashout" in cashout.iloc[7]["rule_flags"]


def test_rule_engine_country_flag_is_explicit():
    featured = engineer_features(synthetic_transactions())
    scored = run_rules(featured)
    assert "high_risk_country" in scored.iloc[8]["rule_flags"]
    assert all(0 <= value <= 1 for value in scored["rule_score"])


def test_statistical_scoring_uses_supplied_iqr_bounds():
    frame = pd.DataFrame(
        {
            "from_account": ["A"] * 4 + ["B"] * 2,
            "amount_paid": [100, 100, 100, 10_000, 50, 50],
        }
    )
    scored = run_statistical(frame, iqr_bounds=(0, 1_000))
    assert {"z_score", "iqr_flag", "stat_score"}.issubset(scored.columns)
    assert bool(scored.iloc[3]["iqr_flag"])
    assert scored.iloc[3]["stat_score"] == 1.0
    assert np.isfinite(scored["z_score"]).all()
    assert scored["stat_score"].between(0, 1).all()


@pytest.mark.requires_data
def test_persisted_saml_normal_iqr_baseline_is_available():
    lower, upper = get_saml_iqr_bounds()
    assert lower < upper
    assert upper > 10_000


def test_isolation_forest_scores_obvious_outlier_higher():
    rng = np.random.default_rng(42)
    baseline = pd.DataFrame(
        {
            "txn_count_7d": rng.normal(3, 0.3, 400),
            "rolling_sum_7d": rng.normal(3_000, 200, 400),
            "near_threshold_count": rng.normal(0, 0.05, 400),
            "amount_deviation": rng.normal(0.1, 0.02, 400),
            "velocity_1hr": rng.normal(1, 0.05, 400),
            "fan_in_count": rng.normal(1, 0.05, 400),
        }
    )
    bundle = train_isolation_forest(
        baseline,
        contamination=0.02,
        n_estimators=100,
    )
    candidates = pd.DataFrame(
        [
            [3, 3_000, 0, 0.1, 1, 1],
            [100, 1_000_000, 50, 20, 40, 80],
        ],
        columns=FEATURES,
    )
    scored = run_ml(candidates, model_bundle=bundle)
    assert scored["ml_score"].between(0, 1).all()
    assert scored.iloc[1]["ml_score"] > scored.iloc[0]["ml_score"]
    assert scored.iloc[1]["anomaly_label"] == 1


@pytest.mark.requires_data
def test_real_saml_model_trains_on_50000_normal_rows():
    bundle = get_model_bundle()
    assert bundle.training_rows == 50_000
