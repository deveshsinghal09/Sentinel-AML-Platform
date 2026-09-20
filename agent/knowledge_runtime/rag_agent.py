"""Retrieval-grounded AML explanation context without unsupported generation."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agent.knowledge_runtime.retriever import (
    AMLKnowledgeRetriever,
    RetrievedKnowledge,
)


class GroundedAMLContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    typology: str | None = None
    supported: bool
    summary: str
    citations: list[str] = Field(default_factory=list)
    evidence: list[RetrievedKnowledge] = Field(default_factory=list)


class AMLKnowledgeAgent:
    """Retrieve regulatory context and clearly disclose unsupported requests."""

    def __init__(self, retriever: AMLKnowledgeRetriever | None = None):
        self._retriever = retriever or AMLKnowledgeRetriever()

    def ground(
        self,
        query: str,
        *,
        typology: str | None = None,
        flags: list[str] | None = None,
    ) -> GroundedAMLContext:
        flag_text = " ".join(flags or [])
        evidence = self._retriever.search(
            f"{query} {flag_text}",
            typology=typology,
            top_k=2,
        )
        if not evidence:
            return GroundedAMLContext(
                typology=typology,
                supported=False,
                summary=(
                    "No matching AML guidance was found in the governed "
                    "knowledge corpus; a regulatory conclusion is not supported."
                ),
            )

        titles = "; ".join(item.title for item in evidence)
        return GroundedAMLContext(
            typology=typology,
            supported=True,
            summary=(
                f"Retrieved context for {typology or 'the detected activity'} "
                f"from {titles}. The alert remains an indicator requiring "
                "analyst review, not a conclusion of money laundering."
            ),
            citations=[item.source for item in evidence],
            evidence=evidence,
        )
