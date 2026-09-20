from __future__ import annotations

import pandas as pd
import pytest

from tools.ml_engine import run_ml, train_isolation_forest


@pytest.fixture(scope="module")
def small_model():
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2022-09-01", periods=30, freq="h"),
            "from_account": [f"A{i % 5}" for i in range(30)],
            "to_account": [f"B{i % 7}" for i in range(30)],
            "amount_paid": [100.0 + i for i in range(30)],
        }
    )
    return train_isolation_forest(frame, contamination=0.1, n_estimators=20)


def test_run_ml_adds_iso_score_and_anomaly_label(sample_transactions, small_model):
    result = run_ml(sample_transactions, model_bundle=small_model)
    assert {"iso_score", "anomaly_label", "ml_score"}.issubset(result.columns)


def test_anomaly_label_is_binary(sample_transactions, small_model):
    result = run_ml(sample_transactions, model_bundle=small_model)
    assert set(result["anomaly_label"]).issubset({0, 1})


def test_ml_score_in_range_0_to_1(sample_transactions, small_model):
    result = run_ml(sample_transactions, model_bundle=small_model)
    assert result["ml_score"].between(0, 1).all()


def test_fewer_than_ten_rows_returns_safely(sample_transactions, small_model):
    result = run_ml(sample_transactions.iloc[:3], model_bundle=small_model)
    assert len(result) == 3
    assert result["ml_score"].notna().all()
