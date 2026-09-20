"""Governed risk-policy, model-card, and monitoring read models."""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from agent.risk.policy import RiskPolicy
from api.monitoring.drift_monitor import DriftReport, ModelDriftMonitor


MODEL_ID = "sentinel-saml-iforest-v1"


class GovernanceNotFound(LookupError):
    pass


class GovernanceUnavailable(RuntimeError):
    pass


class DriftSnapshotProvider(Protocol):
    def snapshots(
        self, model_id: str
    ) -> tuple[dict[str, list[float]], dict[str, list[float]]] | None: ...


class EmptyDriftSnapshotProvider:
    """Production-safe default until a governed monitoring job publishes data."""

    def snapshots(self, model_id: str):
        return None


class GovernanceService:
    def __init__(
        self,
        snapshot_provider: DriftSnapshotProvider,
        *,
        drift_monitor: ModelDriftMonitor | None = None,
        risk_policy: RiskPolicy | None = None,
    ):
        self._snapshots = snapshot_provider
        self._drift = drift_monitor or ModelDriftMonitor()
        self._policy = risk_policy or RiskPolicy()

    def policy(self) -> dict[str, Any]:
        return {
            "version": self._policy.version,
            "jurisdiction": "institution-configured",
            "mode": "read_only",
            "thresholds": {
                "medium": self._policy.medium_threshold,
                "high": self._policy.high_threshold,
            },
            "detector_weights": self._policy.detector_weights,
            "high_risk_country_boost": self._policy.high_risk_country_boost,
            "limitations": [
                "Risk scores are decision support and require analyst review.",
                "Threshold changes require model-risk and compliance approval.",
            ],
        }

    def model_card(self, model_id: str) -> dict[str, Any]:
        if model_id != MODEL_ID:
            raise GovernanceNotFound("Model not found")
        drift = self.drift(model_id)
        return {
            "model_id": MODEL_ID,
            "model_type": "unsupervised anomaly detection",
            "algorithm": "Isolation Forest",
            "library": "scikit-learn",
            "model_version": "1.0.0",
            "training_dataset": "SAML-D normal-behaviour baseline",
            "training_strategy": (
                "Fit on governed normal-behaviour AML features; use rules and "
                "statistics as independent evidence channels."
            ),
            "features": [
                "txn_count_7d",
                "rolling_sum_7d",
                "near_threshold_count",
                "amount_deviation",
                "velocity_1hr",
                "fan_in_count",
            ],
            "contamination": 0.001,
            "random_state": 42,
            "status": "active",
            "drift_status": drift.status,
            "limitations": [
                "Anomaly scores do not establish criminal activity.",
                "Performance depends on representative feature baselines.",
                "Analyst disposition feedback is not yet used for retraining.",
            ],
        }

    def drift(self, model_id: str) -> DriftReport:
        if model_id != MODEL_ID:
            raise GovernanceNotFound("Model not found")
        try:
            snapshots = self._snapshots.snapshots(model_id)
            if snapshots is None:
                return self._drift.not_evaluated(
                    model_id,
                    "No governed current-batch snapshot has been published.",
                )
            baseline, current = snapshots
            return self._drift.evaluate(model_id, baseline, current)
        except GovernanceNotFound:
            raise
        except Exception as exc:
            raise GovernanceUnavailable("Model monitoring unavailable") from exc


@lru_cache(maxsize=1)
def get_governance_service() -> GovernanceService:
    return GovernanceService(EmptyDriftSnapshotProvider())
