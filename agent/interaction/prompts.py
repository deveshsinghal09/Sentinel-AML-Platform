"""Reviewer-facing clarification copy kept separate from decision logic."""
from __future__ import annotations


CLARIFICATION_PROMPTS = {
    "query": "What AML question should Sentinel investigate?",
    "pattern_type": (
        "Which suspicious pattern should be investigated "
        "(for example structuring, layering, or rapid cash-out)?"
    ),
    "entity_id": "Which customer or account ID should be investigated?",
}

CLARIFICATION_OPTIONS = {
    "pattern_type": (
        "structuring",
        "smurfing",
        "layering",
        "rapid_cashout",
        "behavioural_change",
    ),
}


def clarification_prompt(field: str) -> str:
    """Return controlled UI copy without echoing untrusted user text."""

    try:
        return CLARIFICATION_PROMPTS[field]
    except KeyError as exc:
        raise ValueError(f"unsupported clarification field: {field}") from exc
