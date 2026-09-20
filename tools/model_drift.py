"""Population Stability Index monitoring for the active Isolation Forest."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from tools.ml_engine import FEATURES, IsolationForestBundle, get_model_bundle


CAUTION_THRESHOLD = 0.10
DRIFT_THRESHOLD = 0.20


def compute_psi(
    expected: np.ndarray,
    actual: np.ndarray,
    buckets: int = 10,
) -> float:
    """Return PSI using expected-distribution quantiles and stable smoothing."""
    if buckets < 2:
        raise ValueError("buckets must be at least 2")
    expected_values = np.asarray(expected, dtype=float)
    actual_values = np.asarray(actual, dtype=float)
    expected_values = expected_values[np.isfinite(expected_values)]
    actual_values = actual_values[np.isfinite(actual_values)]
    if not len(expected_values) or not len(actual_values):
        return 0.0

    quantiles = np.quantile(
        expected_values,
        np.linspace(0.0, 1.0, buckets + 1),
    )
    edges = np.unique(quantiles)
    if len(edges) < 2:
        center = float(edges[0])
        spread = max(abs(center) * 0.01, 1.0)
        edges = np.array([center - spread, center + spread])
    edges[0] = -np.inf
    edges[-1] = np.inf

    expected_counts = np.histogram(expected_values, bins=edges)[0]
    actual_counts = np.histogram(actual_values, bins=edges)[0]
    epsilon = 1e-6
    expected_pct = np.maximum(expected_counts / len(expected_values), epsilon)
    actual_pct = np.maximum(actual_counts / len(actual_values), epsilon)
    return float(
        np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct))
    )


def _status(psi: float) -> str:
    if psi > DRIFT_THRESHOLD:
        return "drift"
    if psi >= CAUTION_THRESHOLD:
        return "caution"
    return "stable"


def compute_drift_report(
    current_df: pd.DataFrame,
    model_bundle: IsolationForestBundle | None = None,
) -> dict[str, Any]:
    """Compare a current batch with the exact model-training feature baseline."""
    from tools.feature_engineering import engineer_features

    bundle = model_bundle or get_model_bundle()
    featured = engineer_features(
        current_df,
        pattern_types=[],
        require_model_features=True,
    )
    features: list[dict[str, Any]] = []
    for feature in FEATURES:
        current = (
            pd.to_numeric(featured.get(feature), errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
            .to_numpy(dtype=float)
        )
        psi = compute_psi(bundle.reference_features[feature], current)
        features.append(
            {
                "feature": feature,
                "psi": round(psi, 6),
                "status": _status(psi),
                "baseline_mean": round(
                    float(np.mean(bundle.reference_features[feature])),
                    6,
                ),
                "current_mean": round(float(np.mean(current)), 6)
                if len(current)
                else 0.0,
            }
        )
    overall_psi = max((item["psi"] for item in features), default=0.0)
    return {
        "model_id": "sentinel-saml-iforest-v1",
        "method": "population_stability_index",
        "status": _status(overall_psi),
        "overall_psi": overall_psi,
        "thresholds": {
            "stable_below": CAUTION_THRESHOLD,
            "drift_above": DRIFT_THRESHOLD,
        },
        "baseline_rows": bundle.training_rows,
        "current_rows": int(len(featured)),
        "features": features,
        "compared_at": datetime.now(timezone.utc).isoformat(),
        "interpretation": (
            "PSI is a distribution-shift indicator, not proof of model "
            "performance degradation. A compliance model owner must review "
            "drift before recalibration."
        ),
    }
