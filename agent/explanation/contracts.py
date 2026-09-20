"""Contracts for evidence-faithful, reviewer-facing AML narration."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NarrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    risk_score: float = Field(ge=0, le=1)
    risk_label: str
    escalation_action: str
    typology: str | None = None
    rule_flags: list[str] = Field(default_factory=list)
    transaction_count: int = Field(default=0, ge=0)
    total_amount: float = Field(default=0, ge=0)
    observation_window: tuple[str, str] | None = None
    distinct_counterparties: int = Field(default=0, ge=0)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class EvidenceNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    explanation: str
    evidence_points: list[str]
    recommendation: str
    citations: list[str]
    limitations: list[str] = Field(default_factory=list)
