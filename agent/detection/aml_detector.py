"""Selective coordinator for independently testable AML detector tools."""
from __future__ import annotations

from collections import defaultdict

from agent.detection.contracts import (
    DetectionFinding,
    DetectionRequest,
    DetectionSignal,
    DetectorRegistry,
)
from agent.orchestration.contracts import AdaptiveExecutionPlan


_DETECTOR_TOOLS = {
    "rule_engine",
    "statistical_engine",
    "ml_engine",
    "graph_engine",
}


class AMLDetectionAgent:
    """Invoke only detector adapters explicitly selected by the planner."""

    def __init__(self, detectors: DetectorRegistry):
        self._detectors = dict(detectors)

    def detect(
        self,
        request: DetectionRequest,
        plan: AdaptiveExecutionPlan,
    ) -> list[DetectionFinding]:
        if request.query != plan.query:
            raise ValueError("detection request must match the execution plan")

        selected = [
            tool
            for tool in plan.selected_tools()
            if tool in _DETECTOR_TOOLS
        ]
        missing = [tool for tool in selected if tool not in self._detectors]
        if missing:
            raise ValueError(
                "selected detector adapters are unavailable: "
                + ", ".join(sorted(missing))
            )

        grouped: dict[str, list[DetectionSignal]] = defaultdict(list)
        for tool in selected:
            for raw_signal in self._detectors[tool].detect(request):
                signal = DetectionSignal.model_validate(raw_signal)
                if signal.detector != tool:
                    raise ValueError(
                        f"{tool} returned a signal labelled {signal.detector}"
                    )
                grouped[signal.entity_id].append(signal)

        findings: list[DetectionFinding] = []
        for entity_id, signals in grouped.items():
            flags = sorted(
                {
                    flag
                    for signal in signals
                    for flag in signal.flags
                }
            )
            findings.append(
                DetectionFinding(
                    entity_id=entity_id,
                    signals=signals,
                    strongest_score=max(signal.score for signal in signals),
                    flags=flags,
                )
            )
        return sorted(
            findings,
            key=lambda finding: (-finding.strongest_score, finding.entity_id),
        )
