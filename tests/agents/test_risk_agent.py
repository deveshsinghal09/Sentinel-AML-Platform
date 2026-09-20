from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.detection.contracts import DetectionFinding, DetectionSignal
from agent.risk.policy import RiskPolicy
from agent.risk.risk_agent import RiskDecisionAgent


def _signal(detector, score, **evidence):
    return DetectionSignal(
        entity_id="C-100",
        detector=detector,
        score=score,
        flags=[detector.upper()],
        evidence=evidence,
    )


def test_risk_agent_rebalances_weights_across_detectors_that_ran():
    finding = DetectionFinding(
        entity_id="C-100",
        signals=[
            _signal("rule_engine", 0.8),
            _signal("statistical_engine", 0.5),
        ],
        strongest_score=0.8,
        flags=["STRUCTURING"],
    )

    decision = RiskDecisionAgent().decide(finding)

    # 0.4 and 0.2 normalize to 2/3 and 1/3; skipped ML/graph add no zeros.
    assert decision.risk_score == pytest.approx(0.7, abs=1e-6)
    assert decision.risk_label == "medium"
    assert decision.escalation_action == "flag_for_review"
    assert sum(item.normalized_weight for item in decision.contributions) == pytest.approx(1)


def test_high_risk_country_boost_is_explicit_and_capped():
    finding = DetectionFinding(
        entity_id="C-100",
        signals=[_signal("rule_engine", 0.72, high_risk_country=True)],
        strongest_score=0.72,
        flags=["STRUCTURING"],
    )

    decision = RiskDecisionAgent().decide(finding)

    assert decision.country_boost == 0.08
    assert decision.risk_score == 0.8
    assert decision.risk_label == "high"
    assert decision.escalation_action == "report"
    assert "jurisdiction boost" in decision.rationale


def test_empty_evidence_produces_monitor_decision_not_false_confidence():
    finding = DetectionFinding(
        entity_id="C-100",
        signals=[],
        strongest_score=0,
        flags=[],
    )

    decision = RiskDecisionAgent().decide(finding)

    assert decision.risk_score == 0
    assert decision.risk_label == "low"
    assert decision.escalation_action == "monitor"
    assert decision.contributions == []


def test_invalid_policy_thresholds_are_rejected():
    with pytest.raises(ValidationError, match="medium threshold"):
        RiskPolicy(medium_threshold=0.8, high_threshold=0.7)
