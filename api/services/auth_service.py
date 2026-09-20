"""Authentication domain service with opaque, revocable analyst sessions."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from api.security.passwords import hash_password, verify_password


AnalystRole = Literal[
    "analyst",
    "senior_analyst",
    "supervisor",
    "compliance_admin",
    "auditor",
]
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}$")
_DUMMY_PASSWORD_HASH = hash_password(
    "sentinel-invalid-password",
    salt=b"sentinel-dummy-1",
)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: SecretStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not _EMAIL.fullmatch(normalized):
            raise ValueError("A valid email address is required")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        password = value.get_secret_value()
        if not 8 <= len(password) <= 256:
            raise ValueError(
                "Password must contain between 8 and 256 characters"
            )
        return value


class AuthUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=120)
    roles: list[AnalystRole] = Field(min_length=1, max_length=8)


class AuthSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: AuthUser
    expires_at: str


@dataclass(frozen=True, slots=True)
class UserCredential:
    user: AuthUser
    password_hash: str
    enabled: bool = True


@dataclass(slots=True)
class _SessionRecord:
    user_id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


class AuthenticationError(RuntimeError):
    """Base error intentionally carrying no credential detail."""


class InvalidCredentials(AuthenticationError):
    pass


class AuthenticationUnavailable(AuthenticationError):
    pass


class TooManyAttempts(AuthenticationError):
    def __init__(self, retry_after_seconds: int):
        super().__init__("Authentication temporarily rate limited")
        self.retry_after_seconds = max(1, retry_after_seconds)


class AuthenticationService:
    """Thread-safe in-process service with hashed opaque session identifiers."""

    def __init__(
        self,
        credentials: Iterable[UserCredential],
        *,
        session_ttl: timedelta = timedelta(hours=8),
        idle_ttl: timedelta = timedelta(minutes=30),
        attempt_window: timedelta = timedelta(minutes=15),
        lockout_ttl: timedelta = timedelta(minutes=15),
        max_failures: int = 5,
        max_sessions: int = 10_000,
        clock: Callable[[], datetime] | None = None,
    ):
        users = list(credentials)
        self._credentials = {
            item.user.email.strip().casefold(): item for item in users
        }
        self._users_by_id = {item.user.user_id: item.user for item in users}
        if len(self._credentials) != len(users):
            raise ValueError("Configured authentication emails must be unique")
        if len(self._users_by_id) != len(users):
            raise ValueError("Configured authentication user IDs must be unique")
        if max_failures < 1 or max_sessions < 1:
            raise ValueError("Authentication limits must be positive")
        self._session_ttl = session_ttl
        self._idle_ttl = idle_ttl
        self._attempt_window = attempt_window
        self._lockout_ttl = lockout_ttl
        self._max_failures = max_failures
        self._max_sessions = max_sessions
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sessions: dict[str, _SessionRecord] = {}
        self._failures: dict[str, deque[datetime]] = defaultdict(deque)
        self._locked_until: dict[str, datetime] = {}
        self._lock = RLock()

    @staticmethod
    def _token_key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def _attempt_key(self, email: str, client_key: str) -> str:
        value = f"{email.casefold()}|{client_key.strip().casefold()}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _check_rate_limit(self, key: str, now: datetime) -> None:
        locked_until = self._locked_until.get(key)
        if locked_until is None:
            return
        if locked_until <= now:
            self._locked_until.pop(key, None)
            self._failures.pop(key, None)
            return
        raise TooManyAttempts(int((locked_until - now).total_seconds()) + 1)

    def _record_failure(self, key: str, now: datetime) -> None:
        attempts = self._failures[key]
        cutoff = now - self._attempt_window
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        attempts.append(now)
        if len(attempts) >= self._max_failures:
            locked_until = now + self._lockout_ttl
            self._locked_until[key] = locked_until
            raise TooManyAttempts(int(self._lockout_ttl.total_seconds()))

    def _sweep_sessions(self, now: datetime) -> None:
        expired = [
            key
            for key, record in self._sessions.items()
            if record.expires_at <= now
            or record.last_seen_at + self._idle_ttl <= now
        ]
        for key in expired:
            self._sessions.pop(key, None)
        if len(self._sessions) < self._max_sessions:
            return
        oldest = min(
            self._sessions,
            key=lambda key: self._sessions[key].last_seen_at,
        )
        self._sessions.pop(oldest, None)

    def authenticate(
        self,
        email: str,
        password: str,
        *,
        client_key: str,
    ) -> tuple[AuthSession, str]:
        normalized = email.strip().casefold()
        attempt_key = self._attempt_key(normalized, client_key)
        now = self._now()
        with self._lock:
            self._check_rate_limit(attempt_key, now)
            credential = self._credentials.get(normalized)
            password_hash = (
                credential.password_hash
                if credential is not None
                else _DUMMY_PASSWORD_HASH
            )

        verified = verify_password(password, password_hash)
        if credential is None or not credential.enabled or not verified:
            with self._lock:
                self._record_failure(attempt_key, now)
            raise InvalidCredentials("Credentials were not accepted")

        token = secrets.token_urlsafe(32)
        expires_at = now + self._session_ttl
        with self._lock:
            self._failures.pop(attempt_key, None)
            self._locked_until.pop(attempt_key, None)
            self._sweep_sessions(now)
            self._sessions[self._token_key(token)] = _SessionRecord(
                user_id=credential.user.user_id,
                created_at=now,
                last_seen_at=now,
                expires_at=expires_at,
            )
        return (
            AuthSession(
                user=credential.user,
                expires_at=expires_at.isoformat().replace("+00:00", "Z"),
            ),
            token,
        )

    def resolve_session(self, token: str | None) -> AuthSession | None:
        if not token or len(token) > 256:
            return None
        now = self._now()
        key = self._token_key(token)
        with self._lock:
            record = self._sessions.get(key)
            if record is None:
                return None
            if (
                record.expires_at <= now
                or record.last_seen_at + self._idle_ttl <= now
            ):
                self._sessions.pop(key, None)
                return None
            user = self._users_by_id.get(record.user_id)
            if user is None:
                self._sessions.pop(key, None)
                return None
            record.last_seen_at = now
            return AuthSession(
                user=user,
                expires_at=record.expires_at.isoformat().replace(
                    "+00:00",
                    "Z",
                ),
            )

    def revoke_session(self, token: str | None) -> None:
        if not token or len(token) > 256:
            return
        with self._lock:
            self._sessions.pop(self._token_key(token), None)


def _runtime_credentials() -> list[UserCredential]:
    raw = os.environ.get("SENTINEL_AUTH_USERS_JSON", "").strip()
    if not raw:
        raise AuthenticationUnavailable(
            "Authentication identities are not configured"
        )
    try:
        payload = json.loads(raw)
        if not isinstance(payload, list) or not payload:
            raise ValueError("Expected a non-empty list")
        credentials = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("Each identity must be an object")
            user = AuthUser.model_validate(
                {
                    key: item[key]
                    for key in ("user_id", "email", "display_name", "roles")
                }
            )
            credentials.append(
                UserCredential(
                    user=user,
                    password_hash=str(item["password_hash"]),
                    enabled=bool(item.get("enabled", True)),
                )
            )
        return credentials
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AuthenticationUnavailable(
            "Authentication identities are invalid"
        ) from exc


@lru_cache(maxsize=1)
def get_runtime_authentication_service() -> AuthenticationService:
    """Build the process service once; deployments must configure identities."""

    return AuthenticationService(_runtime_credentials())
