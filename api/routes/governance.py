"""Authenticated, read-only AML policy and model-governance endpoints."""
from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status

from api.monitoring.drift_monitor import DriftReport
from api.security.dependencies import require_authenticated_session
from api.services.auth_service import AuthSession
from api.services.governance_service import (
    GovernanceNotFound,
    GovernanceService,
    GovernanceUnavailable,
    get_governance_service,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/governance", tags=["governance"])
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_ROLES = {"senior_analyst", "supervisor", "compliance_admin"}


def require_governance_session(
    session: AuthSession = Depends(require_authenticated_session),
) -> AuthSession:
    if not _ROLES.intersection(session.user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role cannot access model governance.",
        )
    return session


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _execute(operation):
    try:
        return operation()
    except GovernanceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Governed model not found.",
        ) from exc
    except GovernanceUnavailable as exc:
        logger.exception("Model governance operation failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model governance is temporarily unavailable.",
        ) from exc


@router.get("/policy")
def risk_policy(
    response: Response,
    _: AuthSession = Depends(require_governance_session),
    service: GovernanceService = Depends(get_governance_service),
) -> dict[str, Any]:
    _no_store(response)
    return _execute(service.policy)


@router.get("/models/{model_id}")
def model_card(
    response: Response,
    model_id: str = Path(pattern=_MODEL_ID.pattern),
    _: AuthSession = Depends(require_governance_session),
    service: GovernanceService = Depends(get_governance_service),
) -> dict[str, Any]:
    _no_store(response)
    return _execute(lambda: service.model_card(model_id))


@router.get("/models/{model_id}/drift", response_model=DriftReport)
def model_drift(
    response: Response,
    model_id: str = Path(pattern=_MODEL_ID.pattern),
    _: AuthSession = Depends(require_governance_session),
    service: GovernanceService = Depends(get_governance_service),
) -> DriftReport:
    _no_store(response)
    return _execute(lambda: service.drift(model_id))
