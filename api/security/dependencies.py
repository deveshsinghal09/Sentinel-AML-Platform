"""Reusable FastAPI dependencies for authenticated API boundaries."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from api.security.sessions import (
    SessionCookiePolicy,
    get_session_cookie_policy,
)
from api.services.auth_service import (
    AuthSession,
    AuthenticationService,
    AuthenticationUnavailable,
    get_runtime_authentication_service,
)


def get_authentication_service() -> AuthenticationService:
    try:
        return get_runtime_authentication_service()
    except AuthenticationUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable.",
            headers={"Cache-Control": "private, no-store"},
        ) from exc


def get_cookie_policy() -> SessionCookiePolicy:
    try:
        return get_session_cookie_policy()
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable.",
            headers={"Cache-Control": "private, no-store"},
        ) from exc


def require_authenticated_session(
    request: Request,
    service: AuthenticationService = Depends(get_authentication_service),
    cookie: SessionCookiePolicy = Depends(get_cookie_policy),
) -> AuthSession:
    session = service.resolve_session(request.cookies.get(cookie.name))
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="An active analyst session is required.",
            headers={"Cache-Control": "private, no-store"},
        )
    return session
