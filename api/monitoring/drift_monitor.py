"""Population Stability Index monitoring with explicit unevaluated state."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class FeatureDrift(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: str
    psi: float = Field(ge=0)
    status: Literal["stable", "caution", "drift"]
    baseline_count: int = Field(ge=0)
    current_count: int = Field(ge=0)


class DriftReport(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_id: str
    status: Literal["not_evaluated", "stable", "caution", "drift"]
    method: str = "population_stability_index"
    overall_psi: float | None = Field(default=None, ge=0)
    stable_below: float = 0.10
    drift_at_or_above: float = 0.20
    evaluated_at: str | None = None
    features: list[FeatureDrift] = Field(default_factory=list)
    interpretation: str


def population_stability_index(
    baseline: Sequence[float],
    current: Sequence[float],
    *,
    buckets: int = 10,
) -> float:
    """Calculate PSI using baseline quantiles and conservative smoothing."""

    if buckets < 2 or buckets > 50:
        raise ValueError("buckets must be between 2 and 50")
    expected = np.asarray(baseline, dtype=float)
    actual = np.asarray(current, dtype=float)
    expected = expected[np.isfinite(expected)]
    actual = actual[np.isfinite(actual)]
    if len(expected) < 2 or len(actual) < 2:
        raise ValueError("baseline and current samples require at least two values")

    edges = np.unique(
        np.quantile(expected, np.linspace(0.0, 1.0, buckets + 1))
    )
    if len(edges) < 2:
        center = float(edges[0])
        spread = max(abs(center) * 0.01, 1.0)
        edges = np.array([center - spread, center + spread])
    edges[0] = -np.inf
    edges[-1] = np.inf
    expected_counts = np.histogram(expected, bins=edges)[0]
    actual_counts = np.histogram(actual, bins=edges)[0]
    epsilon = 1e-6
    expected_rate = np.maximum(expected_counts / len(expected), epsilon)
    actual_rate = np.maximum(actual_counts / len(actual), epsilon)
    return float(
        np.sum((actual_rate - expected_rate) * np.log(actual_rate / expected_rate))
    )


class ModelDriftMonitor:
    """Evaluate only features present in both governed snapshots."""

    def evaluate(
        self,
        model_id: str,
        baseline: Mapping[str, Sequence[float]],
        current: Mapping[str, Sequence[float]],
    ) -> DriftReport:
        shared = sorted(set(baseline).intersection(current))
        if not shared:
            return self.not_evaluated(
                model_id,
                "No shared governed model features are available for comparison.",
            )
        features: list[FeatureDrift] = []
        for feature in shared:
            psi = population_stability_index(
                baseline[feature],
                current[feature],
            )
            features.append(
                FeatureDrift(
                    feature=feature,
                    psi=round(psi, 6),
                    status=self._status(psi),
                    baseline_count=len(baseline[feature]),
                    current_count=len(current[feature]),
                )
            )
        overall = max(item.psi for item in features)
        return DriftReport(
            model_id=model_id,
            status=self._status(overall),
            overall_psi=overall,
            evaluated_at=datetime.now(UTC).isoformat(),
            features=features,
            interpretation=(
                "PSI indicates feature-distribution shift, not model accuracy "
                "or proof of suspicious activity. A model owner must review "
                "material drift before recalibration."
            ),
        )

    @staticmethod
    def not_evaluated(model_id: str, reason: str) -> DriftReport:
        return DriftReport(
            model_id=model_id,
            status="not_evaluated",
            interpretation=reason,
        )

    @staticmethod
    def _status(psi: float) -> Literal["stable", "caution", "drift"]:
        if psi >= 0.20:
            return "drift"
        if psi >= 0.10:
            return "caution"
        return "stable"
