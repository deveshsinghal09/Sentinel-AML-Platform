"""Evidence-backed Plotly-compatible chart specifications for reviewers."""
from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field

from api.routes.investigations import (
    InvestigationRepository,
    get_investigation_repository,
    record_payload,
)


logger = logging.getLogger(__name__)

_INVESTIGATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_RISK_ORDER = ("low", "medium", "high")

router = APIRouter(prefix="/charts", tags=["charts"])


class ChartSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_id: str
    title: str
    data: list[dict[str, Any]]
    layout: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


class InvestigationChartSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investigation_id: str
    charts: list[ChartSpecification]


def _risk_chart(response: dict[str, Any]) -> ChartSpecification:
    entities = response.get("top_entities") or []
    counts = {
        label: sum(
            str(entity.get("risk_label", "")).casefold() == label
            for entity in entities
            if isinstance(entity, dict)
        )
        for label in _RISK_ORDER
    }
    return ChartSpecification(
        chart_id="risk-distribution",
        title="Flagged entities by risk level",
        data=[
            {
                "type": "bar",
                "x": list(_RISK_ORDER),
                "y": [counts[label] for label in _RISK_ORDER],
                "marker": {
                    "color": ["#34d399", "#fbbf24", "#fb7185"],
                },
                "hovertemplate": "%{x}: %{y}<extra></extra>",
            }
        ],
        layout={
            "xaxis": {"title": "Risk level"},
            "yaxis": {"title": "Flagged entities", "rangemode": "tozero"},
        },
        meta={
            "source": "top_entities.risk_label",
            "record_count": len(entities),
        },
    )


def _tool_chart(response: dict[str, Any]) -> ChartSpecification:
    trace = [
        item
        for item in response.get("execution_trace") or []
        if isinstance(item, dict)
    ]
    tools = [str(item.get("tool", "unknown")) for item in trace]
    durations = [
        max(0.0, float(item.get("duration_ms", 0) or 0))
        for item in trace
    ]
    statuses = [str(item.get("status", "skipped")) for item in trace]
    return ChartSpecification(
        chart_id="tool-execution",
        title="Agent tool execution time",
        data=[
            {
                "type": "bar",
                "orientation": "h",
                "y": tools,
                "x": durations,
                "marker": {
                    "color": [
                        "#6366f1" if item == "run" else "#475569"
                        for item in statuses
                    ],
                },
                "customdata": statuses,
                "hovertemplate": (
                    "%{y}: %{x:.1f} ms · %{customdata}<extra></extra>"
                ),
            }
        ],
        layout={
            "xaxis": {"title": "Duration (ms)", "rangemode": "tozero"},
            "yaxis": {"title": "Tool", "automargin": True},
        },
        meta={
            "source": "execution_trace",
            "ran": sum(item == "run" for item in statuses),
            "skipped": sum(item != "run" for item in statuses),
        },
    )


@router.get(
    "/investigations/{investigation_id}",
    response_model=InvestigationChartSuite,
    summary="Build reviewer charts for one investigation",
)
def investigation_charts(
    response: Response,
    investigation_id: str = Path(
        min_length=1,
        max_length=80,
        pattern=_INVESTIGATION_ID.pattern,
    ),
    repository: InvestigationRepository = Depends(
        get_investigation_repository
    ),
) -> InvestigationChartSuite:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        record = repository.get_investigation(investigation_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Investigation not found.",
                headers={"Cache-Control": "private, no-store"},
            )
        payload = record_payload(record)
        analysis = payload.get("response")
        if not isinstance(analysis, dict):
            raise TypeError("Investigation response is not structured")
        return InvestigationChartSuite(
            investigation_id=investigation_id,
            charts=[_risk_chart(analysis), _tool_chart(analysis)],
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Investigation chart generation failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Investigation charts are temporarily unavailable.",
            headers={"Cache-Control": "private, no-store"},
        ) from exc
