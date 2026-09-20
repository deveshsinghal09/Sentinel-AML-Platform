"""Contracts for query-aware visualization recommendations."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ChartKind = Literal[
    "metric_cards",
    "table",
    "bar",
    "timeline",
    "network",
]


class ChartRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_id: str
    kind: ChartKind
    title: str
    reason: str
    source_fields: tuple[str, ...]
    priority: int = Field(ge=1, le=5)


class VisualizationAdvice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendations: list[ChartRecommendation] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
