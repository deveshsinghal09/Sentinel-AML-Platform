"""Small deterministic AML knowledge retriever with inspectable citations."""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field


_TOKEN = re.compile(r"[a-z0-9]+")


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    title: str
    source: str
    typologies: tuple[str, ...]
    text: str


class RetrievedKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str
    source: str
    excerpt: str
    score: float = Field(ge=0, le=1)


DEFAULT_AML_KNOWLEDGE: tuple[KnowledgeDocument, ...] = (
    KnowledgeDocument(
        document_id="fincen-structuring",
        title="FinCEN: Structuring",
        source="https://www.fincen.gov/resources/statutes-regulations/guidance",
        typologies=("structuring", "smurfing"),
        text=(
            "Structuring breaks activity into smaller transactions to evade "
            "reporting or recordkeeping thresholds. Relevant evidence includes "
            "repeated sub-threshold transactions over a short period."
        ),
    ),
    KnowledgeDocument(
        document_id="fatf-layering",
        title="FATF: Money laundering stages and methods",
        source="https://www.fatf-gafi.org/en/topics/methods-and-trends.html",
        typologies=("layering", "cycle", "fan_in", "fan_out"),
        text=(
            "Layering obscures the source of funds through complex transfers, "
            "multiple counterparties, circular movement, or rapid movement "
            "across accounts and jurisdictions."
        ),
    ),
    KnowledgeDocument(
        document_id="ffiec-monitoring",
        title="FFIEC BSA/AML Manual: Suspicious activity monitoring",
        source=(
            "https://bsaaml.ffiec.gov/manual/"
            "AssessingComplianceWithBSARegulatoryRequirements/04"
        ),
        typologies=(
            "behavioural_change",
            "rapid_cashout",
            "single_large",
        ),
        text=(
            "Monitoring should compare activity with customer and peer "
            "expectations, document relevant facts, and support review with "
            "transaction evidence rather than treating an alert as proof."
        ),
    ),
)


def _tokens(value: str) -> list[str]:
    return _TOKEN.findall(value.lower())


class AMLKnowledgeRetriever:
    """Rank a bounded local corpus without network or generated facts."""

    def __init__(
        self,
        documents: Sequence[KnowledgeDocument] = DEFAULT_AML_KNOWLEDGE,
    ):
        if not documents:
            raise ValueError("knowledge corpus cannot be empty")
        self._documents = tuple(documents)
        self._token_sets = [
            set(_tokens(f"{doc.title} {' '.join(doc.typologies)} {doc.text}"))
            for doc in self._documents
        ]

    def search(
        self,
        query: str,
        *,
        typology: str | None = None,
        top_k: int = 2,
    ) -> list[RetrievedKnowledge]:
        if top_k < 1 or top_k > 10:
            raise ValueError("top_k must be between 1 and 10")
        query_tokens = _tokens(f"{query} {typology or ''}")
        if not query_tokens:
            return []

        document_frequency = Counter(
            token
            for token in set(query_tokens)
            for token_set in self._token_sets
            if token in token_set
        )
        scored: list[tuple[float, KnowledgeDocument]] = []
        for document, token_set in zip(
            self._documents,
            self._token_sets,
            strict=True,
        ):
            lexical = sum(
                math.log((len(self._documents) + 1) / (document_frequency[token] + 1))
                + 1
                for token in set(query_tokens)
                if token in token_set
            )
            typology_match = (
                2.5
                if typology and typology.lower() in document.typologies
                else 0.0
            )
            raw_score = lexical + typology_match
            if raw_score > 0:
                normalized = min(
                    1.0,
                    raw_score / (len(set(query_tokens)) + 2.5),
                )
                scored.append((normalized, document))

        scored.sort(key=lambda item: (-item[0], item[1].document_id))
        return [
            RetrievedKnowledge(
                document_id=document.document_id,
                title=document.title,
                source=document.source,
                excerpt=document.text,
                score=round(score, 6),
            )
            for score, document in scored[:top_k]
        ]
