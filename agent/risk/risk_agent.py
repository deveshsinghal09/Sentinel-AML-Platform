"""Evidence-reconciling AML risk decision agent."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agent.detection.contracts import DetectionFinding
from agent.risk.policy import RiskPolicy


class DetectorContribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detector: str
    score: float = Field(ge=0, le=1)
    normalized_weight: float = Field(ge=0, le=1)
    contribution: float = Field(ge=0, le=1)


class RiskDecision(BaseModel):
    """Fully inspectable result of one entity-level risk decision."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    risk_score: float = Field(ge=0, le=1)
    risk_label: str
    escalation_action: str
    policy_version: str
    contributions: list[DetectorContribution] = Field(default_factory=list)
    country_boost: float = Field(ge=0, le=1)
    flags: list[str] = Field(default_factory=list)
    rationale: str


class RiskDecisionAgent:
    """Convert selected detector evidence into auditable business decisions."""

    def __init__(self, policy: RiskPolicy | None = None):
        self.policy = policy or RiskPolicy()

    def decide(self, finding: DetectionFinding) -> RiskDecision:
        active = [
            signal
            for signal in finding.signals
            if signal.detector in self.policy.detector_weights
        ]
        active_weight = sum(
            self.policy.detector_weights[signal.detector]
            for signal in active
        )
        contributions: list[DetectorContribution] = []
        base_score = 0.0
        if active_weight:
            for signal in active:
                weight = (
                    self.policy.detector_weights[signal.detector]
                    / active_weight
                )
                contribution = signal.score * weight
                base_score += contribution
                contributions.append(
                    DetectorContribution(
                        detector=signal.detector,
                        score=signal.score,
                        normalized_weight=round(weight, 6),
                        contribution=round(contribution, 6),
                    )
                )

        high_risk_country = any(
            bool(signal.evidence.get("high_risk_country"))
            for signal in active
        )
        country_boost = (
            self.policy.high_risk_country_boost if high_risk_country else 0.0
        )
        score = round(min(1.0, base_score + country_boost), 6)
        label = self.policy.label(score)
        action = self.policy.escalation_for(label)
        rationale = self._rationale(
            finding,
            score,
            label,
            country_boost,
        )
        return RiskDecision(
            entity_id=finding.entity_id,
            risk_score=score,
            risk_label=label,
            escalation_action=action,
            policy_version=self.policy.version,
            contributions=contributions,
            country_boost=country_boost,
            flags=finding.flags,
            rationale=rationale,
        )

    @staticmethod
    def _rationale(
        finding: DetectionFinding,
        score: float,
        label: str,
        country_boost: float,
    ) -> str:
        flags = ", ".join(finding.flags[:3]) or "no named typology flag"
        boost_text = (
            f" A {country_boost:.2f} jurisdiction boost was applied."
            if country_boost
            else ""
        )
        return (
            f"Risk is {label} ({score:.2f}) based on selected detector "
            f"evidence: {flags}.{boost_text}"
        )
