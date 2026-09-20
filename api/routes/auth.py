"""Cookie-session authentication endpoints for governed analyst access."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from api.security.origin import enforce_trusted_origin
from api.security.dependencies import (
    get_authentication_service,
    get_cookie_policy,
)
from api.security.sessions import (
    SessionCookiePolicy,
)
from api.services.auth_service import (
    AuthSession,
    AuthenticationService,
    InvalidCredentials,
    LoginRequest,
    TooManyAttempts,
)


router = APIRouter(prefix="/auth", tags=["authentication"])


def _protect(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"


def _client_key(request: Request) -> str:
    # Proxy middleware may replace ``request.client`` with a verified address.
    # Never trust a caller-supplied forwarding header at this boundary.
    return request.client.host if request.client else "unknown"


@router.post(
    "/login",
    response_model=AuthSession,
    summary="Create an analyst session",
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: AuthenticationService = Depends(get_authentication_service),
    cookie: SessionCookiePolicy = Depends(get_cookie_policy),
) -> AuthSession:
    enforce_trusted_origin(request)
    _protect(response)
    try:
        session, token = service.authenticate(
            payload.email,
            payload.password.get_secret_value(),
            client_key=_client_key(request),
        )
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The credentials were not accepted.",
            headers={"Cache-Control": "private, no-store"},
        ) from exc
    except TooManyAttempts as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Try again later.",
            headers={
                "Cache-Control": "private, no-store",
                "Retry-After": str(exc.retry_after_seconds),
            },
        ) from exc
    response.set_cookie(
        key=cookie.name,
        value=token,
        max_age=cookie.max_age_seconds,
        secure=cookie.secure,
        httponly=True,
        samesite=cookie.same_site,
        path=cookie.path,
    )
    return session


@router.get(
    "/session",
    response_model=AuthSession,
    summary="Resolve the current analyst session",
)
def current_session(
    request: Request,
    response: Response,
    service: AuthenticationService = Depends(get_authentication_service),
    cookie: SessionCookiePolicy = Depends(get_cookie_policy),
) -> AuthSession:
    _protect(response)
    session = service.resolve_session(request.cookies.get(cookie.name))
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="An active analyst session is required.",
            headers={"Cache-Control": "private, no-store"},
        )
    return session


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke the current analyst session",
)
def logout(
    request: Request,
    response: Response,
    service: AuthenticationService = Depends(get_authentication_service),
    cookie: SessionCookiePolicy = Depends(get_cookie_policy),
) -> None:
    enforce_trusted_origin(request)
    service.revoke_session(request.cookies.get(cookie.name))
    response.delete_cookie(
        key=cookie.name,
        path=cookie.path,
        secure=cookie.secure,
        httponly=True,
        samesite=cookie.same_site,
    )
    _protect(response)
