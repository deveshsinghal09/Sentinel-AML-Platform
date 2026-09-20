"""Contracts shared by AML detector adapters and the detection agent."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class DetectionRequest(BaseModel):
    """Filtered evidence passed only to detector tools selected by the planner."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    pattern_type: str | None = None
    records: list[dict[str, Any]] = Field(default_factory=list)
    feature_rows: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DetectionSignal(BaseModel):
    """One evidence-backed score emitted by a detector family."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(min_length=1)
    detector: str = Field(min_length=1)
    score: float = Field(ge=0, le=1)
    flags: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class DetectionFinding(BaseModel):
    """All selected detector signals for one entity, with no hidden weighting."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    signals: list[DetectionSignal]
    strongest_score: float = Field(ge=0, le=1)
    flags: list[str] = Field(default_factory=list)

    def scores_by_detector(self) -> dict[str, float]:
        return {
            signal.detector: signal.score
            for signal in self.signals
        }


class DetectorAdapter(Protocol):
    """Port implemented by rule, statistical, ML, and graph detector tools."""

    def detect(self, request: DetectionRequest) -> Sequence[DetectionSignal]: ...


DetectorRegistry = Mapping[str, DetectorAdapter]
