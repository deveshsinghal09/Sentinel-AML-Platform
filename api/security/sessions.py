"""Secure cookie policy shared by authentication routes."""
from __future__ import annotations

import os
from dataclasses import dataclass

from config import APP_ENV


@dataclass(frozen=True, slots=True)
class SessionCookiePolicy:
    name: str
    secure: bool
    max_age_seconds: int
    path: str = "/"
    same_site: str = "strict"


def _boolean(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def get_session_cookie_policy() -> SessionCookiePolicy:
    """Build a host-only cookie policy; production defaults to Secure."""

    secure = _boolean(
        "SENTINEL_COOKIE_SECURE",
        APP_ENV not in {"development", "test"},
    )
    idle_minutes = int(os.environ.get("SENTINEL_SESSION_IDLE_MINUTES", "30"))
    if not 5 <= idle_minutes <= 480:
        raise ValueError(
            "SENTINEL_SESSION_IDLE_MINUTES must be between 5 and 480"
        )
    return SessionCookiePolicy(
        name="__Host-sentinel_session" if secure else "sentinel_session",
        secure=secure,
        max_age_seconds=idle_minutes * 60,
    )
