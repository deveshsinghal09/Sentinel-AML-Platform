"""Versioned, reviewable policy for AML risk classification and escalation."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RiskPolicy(BaseModel):
    """Business-owned thresholds and detector weights.

    Weights are normalized across detectors that actually ran. This prevents
    selectively skipped tools from artificially lowering a risk score.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "aml-risk-v1"
    detector_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "rule_engine": 0.40,
            "statistical_engine": 0.20,
            "ml_engine": 0.25,
            "graph_engine": 0.15,
        }
    )
    medium_threshold: float = Field(default=0.45, ge=0, le=1)
    high_threshold: float = Field(default=0.75, ge=0, le=1)
    high_risk_country_boost: float = Field(default=0.08, ge=0, le=0.25)

    @model_validator(mode="after")
    def validate_policy(self) -> "RiskPolicy":
        if self.medium_threshold >= self.high_threshold:
            raise ValueError("medium threshold must be below high threshold")
        if not self.detector_weights:
            raise ValueError("at least one detector weight is required")
        if any(weight <= 0 for weight in self.detector_weights.values()):
            raise ValueError("detector weights must be positive")
        return self

    def label(self, score: float) -> str:
        if score >= self.high_threshold:
            return "high"
        if score >= self.medium_threshold:
            return "medium"
        return "low"

    @staticmethod
    def escalation_for(label: str) -> str:
        return {
            "high": "report",
            "medium": "flag_for_review",
            "low": "monitor",
        }[label]
