"""Query-clarification agent for incomplete AML investigation requests."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.interaction.prompts import (
    CLARIFICATION_OPTIONS,
    clarification_prompt,
)


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    prompt: str
    required: bool = True
    options: tuple[str, ...] = ()


class ClarificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "needs_clarification"]
    normalized_query: str
    questions: list[ClarificationQuestion] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class QueryClarificationAgent:
    """Ask only for information that blocks a defensible execution plan."""

    def assess(
        self,
        query: str,
        extracted_intent: dict[str, Any] | None = None,
    ) -> ClarificationResult:
        normalized = " ".join(query.split())
        intent = dict(extracted_intent or {})
        questions: list[ClarificationQuestion] = []
        assumptions: list[str] = []

        if not normalized:
            questions.append(self._question("query"))
        else:
            intent_name = str(intent.get("intent") or "")
            if intent_name == "pattern_search" and not intent.get("pattern_type"):
                questions.append(self._question("pattern_type"))
            if intent_name == "entity_lookup" and not self._entity_id(intent):
                questions.append(self._question("entity_id"))

        filters = intent.get("filters")
        has_date_range = isinstance(filters, dict) and bool(
            filters.get("date_range")
        )
        if normalized and not has_date_range:
            assumptions.append(
                "Use the selected dataset's full available date range."
            )
        if normalized and not intent.get("dataset_id"):
            assumptions.append("Use the analyst's currently active dataset.")

        return ClarificationResult(
            status="needs_clarification" if questions else "ready",
            normalized_query=normalized,
            questions=questions,
            assumptions=assumptions,
        )

    @staticmethod
    def _entity_id(intent: dict[str, Any]) -> str | None:
        filters = intent.get("filters")
        if isinstance(filters, dict) and filters.get("entity_id"):
            return str(filters["entity_id"])
        entities = intent.get("entities")
        if isinstance(entities, list) and entities:
            return str(entities[0])
        return None

    @staticmethod
    def _question(field: str) -> ClarificationQuestion:
        return ClarificationQuestion(
            field=field,
            prompt=clarification_prompt(field),
            options=CLARIFICATION_OPTIONS.get(field, ()),
        )
