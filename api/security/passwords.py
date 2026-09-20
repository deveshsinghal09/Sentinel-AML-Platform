"""Versioned password hashing built from Python's reviewed primitives."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000
MINIMUM_ITERATIONS = 310_000
SALT_BYTES = 16


class PasswordHashError(ValueError):
    """Raised when a stored password hash violates the supported contract."""


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise PasswordHashError("Password hash contains invalid base64") from exc


def hash_password(
    password: str,
    *,
    iterations: int = DEFAULT_ITERATIONS,
    salt: bytes | None = None,
) -> str:
    """Return a self-describing PBKDF2-SHA256 password hash."""

    if not 8 <= len(password) <= 256:
        raise ValueError("Password must contain between 8 and 256 characters")
    if iterations < MINIMUM_ITERATIONS:
        raise ValueError(
            f"PBKDF2 iterations must be at least {MINIMUM_ITERATIONS}"
        )
    selected_salt = salt or secrets.token_bytes(SALT_BYTES)
    if len(selected_salt) < SALT_BYTES:
        raise ValueError(f"Password salt must contain at least {SALT_BYTES} bytes")
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        selected_salt,
        iterations,
    )
    return "$".join(
        (ALGORITHM, str(iterations), _encode(selected_salt), _encode(digest))
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verify without raising on malformed untrusted credential records."""

    try:
        algorithm, raw_iterations, raw_salt, raw_digest = encoded.split("$")
        if algorithm != ALGORITHM:
            raise PasswordHashError("Unsupported password hash algorithm")
        iterations = int(raw_iterations)
        if iterations < MINIMUM_ITERATIONS:
            raise PasswordHashError("Password hash iteration count is too low")
        salt = _decode(raw_salt)
        expected = _decode(raw_digest)
        if len(salt) < SALT_BYTES or len(expected) != hashlib.sha256().digest_size:
            raise PasswordHashError("Password hash has an invalid size")
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(candidate, expected)
    except (PasswordHashError, TypeError, ValueError):
        return False
