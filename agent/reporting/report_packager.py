"""Package agent results into a reproducible reviewer-facing investigation."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.reporting.templates import (
    REPORT_DISCLAIMER,
    REPORT_VERSION,
    citation_warning,
    evidence_warning,
)


class PackagedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    risk_score: float = Field(ge=0, le=1)
    risk_label: str
    escalation_action: str
    explanation: str
    rule_flags: list[str] = Field(default_factory=list)
    transaction_count: int = Field(default=0, ge=0)
    total_amount: float = Field(default=0, ge=0)
    citation: str = ""


class SARDraftPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    draft: str
    status: str = "draft_requires_authorized_review"


class InvestigationPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_version: str
    investigation_id: str
    generated_at: str
    query: str
    intent: dict[str, Any]
    filters: dict[str, Any]
    selected_tools: list[str]
    skipped_tools: list[dict[str, str]]
    plan_rationale: str
    findings: list[PackagedFinding]
    sar_drafts: list[SARDraftPackage]
    citations: list[str]
    warnings: list[str]
    evidence_checksum: str
    disclaimer: str


class ReportPackagingAgent:
    """Build an immutable presentation package from structured agent output."""

    def package(
        self,
        investigation_id: str,
        response: Mapping[str, Any],
        *,
        generated_at: datetime | None = None,
    ) -> InvestigationPackage:
        if not investigation_id.strip():
            raise ValueError("investigation_id cannot be blank")
        query = str(response.get("query") or "").strip()
        if not query:
            raise ValueError("agent response must contain a query")

        intent = self._mapping(response.get("intent"))
        plan = self._mapping(response.get("plan"))
        findings: list[PackagedFinding] = []
        sar_drafts: list[SARDraftPackage] = []
        citations: list[str] = []
        warnings: list[str] = []

        for raw_entity in response.get("top_entities") or []:
            if not isinstance(raw_entity, Mapping):
                warnings.append("A malformed finding was omitted from the package.")
                continue
            entity_id = str(raw_entity.get("entity_id") or "").strip()
            if not entity_id:
                warnings.append("A finding without an entity ID was omitted.")
                continue
            citation = str(raw_entity.get("citation") or "").strip()
            transactions = raw_entity.get("top_transactions")
            if not isinstance(transactions, list) or not transactions:
                warnings.append(evidence_warning(entity_id))
            if not citation:
                warnings.append(citation_warning(entity_id))
            else:
                citations.append(citation)

            finding = PackagedFinding(
                entity_id=entity_id,
                risk_score=float(raw_entity.get("risk_score") or 0),
                risk_label=str(raw_entity.get("risk_label") or "low"),
                escalation_action=str(
                    raw_entity.get("escalation_action") or "monitor"
                ),
                explanation=str(raw_entity.get("explanation") or ""),
                rule_flags=[
                    str(flag)
                    for flag in raw_entity.get("rule_flags") or []
                ],
                transaction_count=int(raw_entity.get("txn_count") or 0),
                total_amount=float(raw_entity.get("total_amount") or 0),
                citation=citation,
            )
            findings.append(finding)

            draft = str(raw_entity.get("sar_draft") or "").strip()
            if (
                draft
                and finding.risk_label == "high"
                and finding.escalation_action == "report"
            ):
                sar_drafts.append(
                    SARDraftPackage(entity_id=entity_id, draft=draft)
                )

        canonical_response = json.dumps(
            response,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        timestamp = generated_at or datetime.now(UTC)
        skipped = [
            {
                "tool": str(item.get("tool") or ""),
                "reason": str(item.get("reason") or ""),
            }
            for item in plan.get("skipped") or []
            if isinstance(item, Mapping)
        ]
        return InvestigationPackage(
            package_version=REPORT_VERSION,
            investigation_id=investigation_id.strip(),
            generated_at=timestamp.astimezone(UTC).isoformat(),
            query=query,
            intent=intent,
            filters=self._mapping(intent.get("filters")),
            selected_tools=[
                str(tool) for tool in plan.get("steps") or []
            ],
            skipped_tools=skipped,
            plan_rationale=str(plan.get("reasoning") or ""),
            findings=findings,
            sar_drafts=sar_drafts,
            citations=list(dict.fromkeys(citations)),
            warnings=warnings,
            evidence_checksum=hashlib.sha256(canonical_response).hexdigest(),
            disclaimer=REPORT_DISCLAIMER,
        )

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}
