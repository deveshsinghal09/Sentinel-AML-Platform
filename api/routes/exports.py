"""Authenticated, bounded exports for persisted investigation evidence."""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status

from api.routes.investigations import (
    InvestigationRepository,
    get_investigation_repository,
    record_payload,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/exports", tags=["exports"])
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_EXPORT_ROLES = {"analyst", "senior_analyst", "supervisor", "compliance_admin"}
_MAX_ENTITIES = 10_000
_MAX_TRACE_STEPS = 2_000


def require_export_access(request: Request) -> object:
    """Resolve server-side session lazily and fail closed on incomplete merges."""

    try:
        from api.security.sessions import get_session_cookie_policy
        from api.services.auth_service import get_runtime_authentication_service
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Export authorization is temporarily unavailable.",
        ) from exc
    cookie = get_session_cookie_policy()
    session = get_runtime_authentication_service().resolve_session(
        request.cookies.get(cookie.name)
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="An active analyst session is required.",
        )
    if not _EXPORT_ROLES.intersection(session.user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role cannot export investigation evidence.",
        )
    return session


def _load(
    repository: InvestigationRepository,
    investigation_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        record = repository.get_investigation(investigation_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Investigation not found.",
            )
        payload = record_payload(record)
        analysis = payload.get("response")
        if not isinstance(analysis, dict):
            raise TypeError("Investigation response is not structured")
        return payload, analysis
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Investigation export failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Investigation export is temporarily unavailable.",
        ) from exc


def _headers(investigation_id: str, filename: str) -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Sentinel-Investigation-Id": investigation_id,
        "X-Content-Type-Options": "nosniff",
    }


def _json_response(
    payload: Any,
    *,
    investigation_id: str,
    filename: str,
) -> Response:
    return Response(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        media_type="application/json",
        headers=_headers(investigation_id, filename),
    )


def _safe_csv(value: Any) -> str:
    rendered = "" if value is None else str(value)
    return f"'{rendered}" if rendered.startswith(("=", "+", "-", "@")) else rendered


def _csv_response(
    rows: list[dict[str, Any]],
    fields: list[str],
    *,
    investigation_id: str,
    filename: str,
) -> Response:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _safe_csv(row.get(field)) for field in fields})
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers=_headers(investigation_id, filename),
    )


@router.get("/investigations/{investigation_id}")
def export_investigation(
    investigation_id: str = Path(pattern=_ID.pattern),
    export_format: Literal["json", "md"] = Query(alias="format"),
    _: object = Depends(require_export_access),
    repository: InvestigationRepository = Depends(get_investigation_repository),
) -> Response:
    payload, analysis = _load(repository, investigation_id)
    if export_format == "json":
        return _json_response(
            payload,
            investigation_id=investigation_id,
            filename=f"investigation_{investigation_id}.json",
        )
    summary = analysis.get("summary_stats") or {}
    plan = analysis.get("plan") or {}
    lines = [
        f"# Investigation {investigation_id}",
        "",
        f"**Query:** {payload.get('query') or analysis.get('query') or ''}",
        f"**Status:** {payload.get('status') or 'unknown'}",
        f"**Dataset:** {payload.get('dataset_name') or payload.get('dataset_id') or 'not recorded'}",
        "",
        "## Agent decision",
        "",
        str(plan.get("reasoning") or "No plan rationale was recorded."),
        "",
        "## Execution plan",
        "",
        *[f"{index}. {tool}" for index, tool in enumerate(plan.get("steps") or [], 1)],
        "",
        "## Results",
        "",
        f"- Analyzed: {summary.get('total_analyzed', 0)}",
        f"- Flagged: {summary.get('flagged', 0)}",
        f"- High risk: {summary.get('high_risk', 0)}",
        "",
        "> Decision-support evidence only. Authorized AML review is required.",
    ]
    return Response(
        "\n".join(lines),
        media_type="text/markdown",
        headers=_headers(investigation_id, f"investigation_{investigation_id}.md"),
    )


@router.get("/investigations/{investigation_id}/entities")
def export_entities(
    investigation_id: str = Path(pattern=_ID.pattern),
    export_format: Literal["csv", "json"] = Query(alias="format"),
    _: object = Depends(require_export_access),
    repository: InvestigationRepository = Depends(get_investigation_repository),
) -> Response:
    _, analysis = _load(repository, investigation_id)
    entities = [
        item
        for item in analysis.get("top_entities") or []
        if isinstance(item, dict)
    ]
    if len(entities) > _MAX_ENTITIES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Entity export exceeds the governed row limit.",
        )
    if export_format == "json":
        return _json_response(
            entities,
            investigation_id=investigation_id,
            filename=f"entities_{investigation_id}.json",
        )
    fields = [
        "entity_id",
        "risk_score",
        "risk_label",
        "escalation_action",
        "saml_d_typology",
        "txn_count",
        "total_amount",
        "explanation",
        "citation",
    ]
    return _csv_response(
        entities,
        fields,
        investigation_id=investigation_id,
        filename=f"entities_{investigation_id}.csv",
    )


@router.get("/investigations/{investigation_id}/trace")
def export_trace(
    investigation_id: str = Path(pattern=_ID.pattern),
    export_format: Literal["csv", "json"] = Query(alias="format"),
    _: object = Depends(require_export_access),
    repository: InvestigationRepository = Depends(get_investigation_repository),
) -> Response:
    _, analysis = _load(repository, investigation_id)
    trace = [
        item
        for item in analysis.get("execution_trace") or []
        if isinstance(item, dict)
    ]
    if len(trace) > _MAX_TRACE_STEPS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Execution trace exceeds the governed row limit.",
        )
    if export_format == "json":
        return _json_response(
            trace,
            investigation_id=investigation_id,
            filename=f"trace_{investigation_id}.json",
        )
    return _csv_response(
        trace,
        ["tool", "status", "duration_ms", "reason"],
        investigation_id=investigation_id,
        filename=f"trace_{investigation_id}.csv",
    )
