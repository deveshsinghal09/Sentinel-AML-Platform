"""Authenticated analyst review queue and immutable audit endpoints."""
from __future__ import annotations

import logging
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.security.dependencies import require_authenticated_session
from api.services.auth_service import AuthSession
from api.services.workflow_service import (
    WorkflowNotFound,
    WorkflowService,
    WorkflowUnavailable,
    get_workflow_service,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflow", tags=["workflow"])
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_ROLES = {"analyst", "senior_analyst", "supervisor", "compliance_admin"}


class AssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assigned_to: str = Field(min_length=1, max_length=120)

    @field_validator("assigned_to")
    @classmethod
    def normalize(cls, value: str) -> str:
        return " ".join(value.split())


class DispositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disposition: Literal["true_positive", "false_positive", "escalated"]


class NoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=4_000)

    @field_validator("note")
    @classmethod
    def normalize(cls, value: str) -> str:
        return " ".join(value.split())


class QueuePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[dict[str, Any]]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class AuditPage(QueuePage):
    pass


def require_workflow_session(
    session: AuthSession = Depends(require_authenticated_session),
) -> AuthSession:
    if not _ROLES.intersection(session.user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role cannot access the review workflow.",
        )
    return session


def _actor(session: AuthSession) -> str:
    return session.user.email


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _execute(operation):
    try:
        return operation()
    except WorkflowNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found.",
        ) from exc
    except WorkflowUnavailable as exc:
        logger.exception("Review workflow operation failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Review workflow is temporarily unavailable.",
        ) from exc


@router.get("/queue", response_model=QueuePage)
def list_queue(
    response: Response,
    workflow_status: Literal["new", "in_review", "escalated", "closed"] | None = None,
    assigned_to: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: AuthSession = Depends(require_workflow_session),
    service: WorkflowService = Depends(get_workflow_service),
) -> QueuePage:
    _no_store(response)
    items, total = _execute(
        lambda: service.list_alerts(
            status=workflow_status,
            assigned_to=assigned_to,
            limit=limit,
            offset=offset,
        )
    )
    return QueuePage(items=items, total=total, limit=limit, offset=offset)


@router.get("/queue/summary")
def queue_summary(
    response: Response,
    _: AuthSession = Depends(require_workflow_session),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, int]:
    _no_store(response)
    return _execute(service.summary)


@router.post("/queue/{alert_id}/assign")
def assign_alert(
    payload: AssignmentRequest,
    response: Response,
    alert_id: str = Path(pattern=_ID.pattern),
    session: AuthSession = Depends(require_workflow_session),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    _no_store(response)
    return _execute(
        lambda: service.assign(alert_id, payload.assigned_to, _actor(session))
    )


@router.post("/queue/{alert_id}/disposition")
def disposition_alert(
    payload: DispositionRequest,
    response: Response,
    alert_id: str = Path(pattern=_ID.pattern),
    session: AuthSession = Depends(require_workflow_session),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    _no_store(response)
    return _execute(
        lambda: service.disposition(alert_id, payload.disposition, _actor(session))
    )


@router.post("/queue/{alert_id}/notes")
def add_alert_note(
    payload: NoteRequest,
    response: Response,
    alert_id: str = Path(pattern=_ID.pattern),
    session: AuthSession = Depends(require_workflow_session),
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    _no_store(response)
    return _execute(lambda: service.append_note(alert_id, payload.note, _actor(session)))


@router.get("/audit", response_model=AuditPage)
def audit_events(
    response: Response,
    alert_id: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: AuthSession = Depends(require_workflow_session),
    service: WorkflowService = Depends(get_workflow_service),
) -> AuditPage:
    _no_store(response)
    items, total = _execute(
        lambda: service.audit(alert_id=alert_id, limit=limit, offset=offset)
    )
    return AuditPage(items=items, total=total, limit=limit, offset=offset)
