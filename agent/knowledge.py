"""
knowledge.py — AML typology knowledge base + BM25 index.

Loads typologies from knowledge_base/typologies.json and the markdown files,
builds a BM25 index over them, and exposes a `lookup(query)` function that
returns the top-k most relevant typology snippets.

Used by:
  - DynamicPlanner (Phase 2): to enrich the plan with pattern context
  - Explanation tool (Phase 4): for grounded citations
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from loguru import logger

_KB_DIR = Path(__file__).resolve().parent.parent / "knowledge_base"


def _load_typologies() -> list[dict]:
    """Return list of typology dicts from typologies.json."""
    path = _KB_DIR / "typologies.json"
    if not path.exists():
        logger.warning(f"typologies.json not found at {path}, returning empty list")
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # data is {pattern_id: {name, threshold, reg_ref, description}}
    return [{"id": k, **v} for k, v in data.items()]


def _load_markdown_docs() -> list[dict]:
    """Return list of {filename, text} dicts for each .md file in knowledge_base/."""
    docs = []
    for md_file in _KB_DIR.glob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        docs.append({"filename": md_file.name, "text": text})
    return docs


def _tokenise(text: str) -> list[str]:
    """Simple whitespace + lowercase tokeniser for BM25."""
    return re.findall(r"[a-z0-9]+", text.lower())


class AMLKnowledge:
    """Thin wrapper around BM25 index over AML typologies + markdown docs."""

    def __init__(self) -> None:
        self._corpus: list[dict] = []
        self._tokenised: list[list[str]] = []
        self._bm25 = None
        self._ready = False

    def build_index(self) -> None:
        """Build the BM25 index. Call once at startup."""
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("rank-bm25 not installed; knowledge lookup disabled")
            return

        typologies = _load_typologies()
        md_docs = _load_markdown_docs()

        for t in typologies:
            text = f"{t.get('name','')} {t.get('description','')} {t.get('reg_ref','')}"
            self._corpus.append({"type": "typology", **t, "text": text})
            self._tokenised.append(_tokenise(text))

        for d in md_docs:
            # Chunk markdown into ~200-token paragraphs
            paragraphs = [p.strip() for p in d["text"].split("\n\n") if p.strip()]
            for para in paragraphs:
                self._corpus.append(
                    {"type": "markdown", "filename": d["filename"], "text": para}
                )
                self._tokenised.append(_tokenise(para))

        if self._tokenised:
            self._bm25 = BM25Okapi(self._tokenised)
            self._ready = True
            logger.info(
                f"AML knowledge index built: {len(self._corpus)} documents"
            )
        else:
            logger.warning("Knowledge base is empty — no .md or typology files found")

    def lookup(self, query: str, top_k: int = 3) -> list[dict]:
        """Return top-k knowledge snippets relevant to *query*.

        Returns an empty list if the index hasn't been built or is empty.
        """
        if not self._ready or self._bm25 is None:
            return []
        tokens = _tokenise(query)
        scores = self._bm25.get_scores(tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [
            {**self._corpus[i], "bm25_score": round(float(scores[i]), 4)}
            for i in top_indices
        ]


# Module-level singleton — built lazily on first use
_knowledge: Optional[AMLKnowledge] = None


def get_knowledge() -> AMLKnowledge:
    """Return (and lazily build) the module-level AMLKnowledge singleton."""
    global _knowledge
    if _knowledge is None:
        _knowledge = AMLKnowledge()
        _knowledge.build_index()
    return _knowledge
