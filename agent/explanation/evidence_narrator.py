"""Deterministic narration of AML evidence without unsupported conclusions."""
from __future__ import annotations

from agent.explanation.contracts import EvidenceNarrative, NarrationRequest


_ACTIONS = {
    "monitor": "Continue monitoring under the current risk policy.",
    "flag_for_review": "Assign this alert to an analyst for evidence review.",
    "report": (
        "Escalate to a senior AML reviewer to determine whether reporting "
        "obligations are met."
    ),
}


class EvidenceNarrationAgent:
    """Translate exact structured evidence into concise reviewer language."""

    def narrate(self, request: NarrationRequest) -> EvidenceNarrative:
        typology = (request.typology or "suspicious activity").replace("_", " ")
        points = self._evidence_points(request)
        limitations: list[str] = []
        if not request.evidence:
            limitations.append(
                "No transaction-level rows were supplied with this summary."
            )
        if not request.citations:
            limitations.append(
                "No regulatory citation was supplied; typology context is ungrounded."
            )

        explanation = (
            f"Entity {request.entity_id} is classified {request.risk_label} "
            f"risk ({request.risk_score:.0%}) for potential {typology}. "
            + " ".join(points)
            + " This is an alert indicator, not a conclusion of illicit activity."
        )
        return EvidenceNarrative(
            headline=(
                f"{request.risk_label.title()} risk · "
                f"{typology.title()} indicator"
            ),
            explanation=explanation,
            evidence_points=points,
            recommendation=_ACTIONS.get(
                request.escalation_action,
                "Route the result to an AML analyst for review.",
            ),
            citations=list(dict.fromkeys(request.citations)),
            limitations=limitations,
        )

    @staticmethod
    def _evidence_points(request: NarrationRequest) -> list[str]:
        points: list[str] = []
        if request.transaction_count:
            amount = f"${request.total_amount:,.2f}"
            points.append(
                f"Observed {request.transaction_count:,} transactions "
                f"totalling {amount}."
            )
        if request.observation_window:
            start, end = request.observation_window
            points.append(f"Activity occurred from {start} through {end}.")
        if request.distinct_counterparties:
            points.append(
                f"Activity involved {request.distinct_counterparties:,} "
                "distinct counterparties."
            )
        if request.rule_flags:
            readable = ", ".join(
                flag.replace("_", " ").lower()
                for flag in request.rule_flags[:4]
            )
            points.append(f"Triggered evidence signals: {readable}.")
        if not points:
            points.append(
                "The supplied result contains a risk decision but no aggregate metrics."
            )
        return points
