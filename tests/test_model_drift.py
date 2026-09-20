from __future__ import annotations

import numpy as np

from tools.ml_engine import train_isolation_forest
from tools.model_drift import compute_drift_report, compute_psi


def test_psi_is_zero_for_identical_distributions():
    values = np.arange(100, dtype=float)
    assert compute_psi(values, values) == 0.0


def test_psi_detects_material_shift():
    baseline = np.linspace(0, 1, 1_000)
    shifted = np.linspace(5, 6, 1_000)
    assert compute_psi(baseline, shifted) > 0.2


def test_drift_report_covers_exact_model_features(sample_transactions):
    baseline = sample_transactions.loc[
        sample_transactions.index.repeat(5)
    ].reset_index(drop=True)
    bundle = train_isolation_forest(
        baseline,
        contamination=0.1,
        n_estimators=20,
    )
    report = compute_drift_report(sample_transactions, bundle)
    assert report["model_id"] == "sentinel-saml-iforest-v1"
    assert report["status"] in {"stable", "caution", "drift"}
    assert report["baseline_rows"] == len(baseline)
    assert report["current_rows"] == len(sample_transactions)
    assert len(report["features"]) == 6
    assert all(item["psi"] >= 0 for item in report["features"])
