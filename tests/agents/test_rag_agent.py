from __future__ import annotations

import pytest

from agent.knowledge_runtime.rag_agent import AMLKnowledgeAgent
from agent.knowledge_runtime.retriever import (
    AMLKnowledgeRetriever,
    KnowledgeDocument,
)


def test_typology_search_prioritizes_matching_regulatory_context():
    results = AMLKnowledgeRetriever().search(
        "repeated payments below reporting threshold",
        typology="structuring",
    )

    assert results[0].document_id == "fincen-structuring"
    assert results[0].score > 0
    assert results[0].source.startswith("https://")


def test_grounded_context_returns_citations_and_non_conclusive_language():
    context = AMLKnowledgeAgent().ground(
        "Eight sub-threshold payments in four days",
        typology="structuring",
        flags=["STRUCTURING", "HIGH_VELOCITY"],
    )

    assert context.supported
    assert context.citations
    assert "analyst review" in context.summary
    assert "conclusion of money laundering" in context.summary


def test_unknown_subject_fails_with_explicit_unsupported_context():
    corpus = (
        KnowledgeDocument(
            document_id="only-structuring",
            title="Structuring note",
            source="https://example.test/structuring",
            typologies=("structuring",),
            text="Repeated sub-threshold deposits can indicate structuring.",
        ),
    )
    agent = AMLKnowledgeAgent(AMLKnowledgeRetriever(corpus))

    context = agent.ground("quantum weather telemetry", typology="unrelated")

    assert not context.supported
    assert context.citations == []
    assert "not supported" in context.summary


@pytest.mark.parametrize("top_k", [0, 11])
def test_retrieval_limit_is_bounded(top_k):
    with pytest.raises(ValueError, match="between 1 and 10"):
        AMLKnowledgeRetriever().search("structuring", top_k=top_k)
