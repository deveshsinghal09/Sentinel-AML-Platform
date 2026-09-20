"""Authenticated natural-language entry point to the AML agent runtime."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status

from agent.models import AgentResponse, QueryRequest
from api.security.dependencies import require_authenticated_session
from api.services.auth_service import AuthSession
from api.services.query_service import (
    QueryCapacityError,
    QueryService,
    QueryValidationError,
    get_query_service,
)


logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])
_QUERY_ROLES = {
    "analyst",
    "senior_analyst",
    "supervisor",
    "compliance_admin",
}


def require_query_session(
    session: AuthSession = Depends(require_authenticated_session),
) -> AuthSession:
    if not _QUERY_ROLES.intersection(session.user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role cannot execute AML investigations.",
            headers={"Cache-Control": "private, no-store"},
        )
    return session


@router.post(
    "/query",
    response_model=AgentResponse,
    summary="Execute a query-aware AML investigation",
)
def execute_query(
    request: QueryRequest,
    response: Response,
    _: AuthSession = Depends(require_query_session),
    service: QueryService = Depends(get_query_service),
) -> AgentResponse:
    """Return the plan, tool trace, risk decisions, and grounded explanations."""

    response.headers["Cache-Control"] = "private, no-store"
    try:
        return service.run(request)
    except QueryCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Investigation capacity is temporarily unavailable.",
            headers={
                "Cache-Control": "private, no-store",
                "Retry-After": str(exc.retry_after_seconds),
            },
        ) from exc
    except QueryValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
            headers={"Cache-Control": "private, no-store"},
        ) from exc
    except Exception as exc:
        logger.exception("AML investigation execution failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AML investigation could not be completed.",
            headers={"Cache-Control": "private, no-store"},
        ) from exc
