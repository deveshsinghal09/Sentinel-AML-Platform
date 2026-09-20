from __future__ import annotations

import pytest

from agent.detection.aml_detector import AMLDetectionAgent
from agent.detection.contracts import DetectionRequest, DetectionSignal
from agent.models import IntentResult
from agent.orchestration.dynamic_planner import DynamicPlanningAgent


class RecordingDetector:
    def __init__(self, detector, signals):
        self.detector = detector
        self.signals = signals
        self.calls = []

    def detect(self, request):
        self.calls.append(request)
        return self.signals


def _signal(detector, entity, score, flag):
    return DetectionSignal(
        entity_id=entity,
        detector=detector,
        score=score,
        flags=[flag],
        evidence={"transaction_count": 8},
    )


def test_detection_agent_invokes_only_planned_detector_tools():
    query = "Find structuring activity"
    plan = DynamicPlanningAgent().build_plan(
        query,
        IntentResult(
            intent="pattern_search",
            pattern_type="structuring",
        ),
    )
    rules = RecordingDetector(
        "rule_engine",
        [_signal("rule_engine", "C-1", 0.8, "STRUCTURING")],
    )
    ml = RecordingDetector(
        "ml_engine",
        [_signal("ml_engine", "C-2", 0.9, "ANOMALY")],
    )

    findings = AMLDetectionAgent(
        {"rule_engine": rules, "ml_engine": ml}
    ).detect(DetectionRequest(query=query), plan)

    assert [finding.entity_id for finding in findings] == ["C-1"]
    assert len(rules.calls) == 1
    assert ml.calls == []


def test_detection_agent_merges_and_ranks_multi_detector_evidence():
    query = "Find rapid cash-out using anomaly detection"
    plan = DynamicPlanningAgent().build_plan(
        query,
        IntentResult(
            intent="pattern_search",
            pattern_type="rapid_cashout",
            require_ml=True,
        ),
    )
    rules = RecordingDetector(
        "rule_engine",
        [
            _signal("rule_engine", "C-1", 0.7, "RAPID_CASHOUT"),
            _signal("rule_engine", "C-2", 0.4, "VELOCITY"),
        ],
    )
    stats = RecordingDetector(
        "statistical_engine",
        [_signal("statistical_engine", "C-1", 0.84, "AMOUNT_DEVIATION")],
    )
    ml = RecordingDetector(
        "ml_engine",
        [_signal("ml_engine", "C-2", 0.91, "MULTIVARIATE_ANOMALY")],
    )

    findings = AMLDetectionAgent(
        {
            "rule_engine": rules,
            "statistical_engine": stats,
            "ml_engine": ml,
        }
    ).detect(DetectionRequest(query=query), plan)

    assert [finding.entity_id for finding in findings] == ["C-2", "C-1"]
    assert findings[1].flags == ["AMOUNT_DEVIATION", "RAPID_CASHOUT"]
    assert findings[1].scores_by_detector() == {
        "rule_engine": 0.7,
        "statistical_engine": 0.84,
    }


def test_missing_selected_adapter_fails_closed():
    query = "Find layering networks"
    plan = DynamicPlanningAgent().build_plan(
        query,
        IntentResult(intent="pattern_search", pattern_type="layering"),
    )

    with pytest.raises(ValueError, match="graph_engine"):
        AMLDetectionAgent({"rule_engine": RecordingDetector("rule_engine", [])}).detect(
            DetectionRequest(query=query),
            plan,
        )


def test_detector_cannot_mislabel_its_evidence():
    query = "Find structuring activity"
    plan = DynamicPlanningAgent().build_plan(
        query,
        IntentResult(intent="pattern_search", pattern_type="structuring"),
    )
    bad_rules = RecordingDetector(
        "rule_engine",
        [_signal("ml_engine", "C-1", 0.8, "WRONG_PROVENANCE")],
    )

    with pytest.raises(ValueError, match="labelled ml_engine"):
        AMLDetectionAgent({"rule_engine": bad_rules}).detect(
            DetectionRequest(query=query),
            plan,
        )
