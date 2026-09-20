"""Controlled text used in reviewer and SAR-draft presentation packages."""
from __future__ import annotations


REPORT_VERSION = "sentinel-investigation-package-v1"
REPORT_DISCLAIMER = (
    "This package contains decision-support indicators, not a determination "
    "that money laundering occurred. An authorized AML reviewer must verify "
    "the evidence and decide whether any regulatory filing is required."
)


def evidence_warning(entity_id: str) -> str:
    return (
        f"{entity_id}: no transaction-level evidence was included; "
        "verify source transactions before disposition."
    )


def citation_warning(entity_id: str) -> str:
    return (
        f"{entity_id}: no AML knowledge citation was included; "
        "typology language requires reviewer grounding."
    )
