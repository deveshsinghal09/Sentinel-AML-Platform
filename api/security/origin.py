"""Same-origin enforcement for browser-authentication state changes."""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

from config import ALLOWED_ORIGINS


def _normalized_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def enforce_trusted_origin(request: Request) -> None:
    """Reject cross-site browser mutations while retaining CLI/API support."""

    origin = request.headers.get("origin")
    if origin is None:
        return
    candidate = _normalized_origin(origin)
    trusted = {
        normalized
        for value in ALLOWED_ORIGINS
        if (normalized := _normalized_origin(value)) is not None
    }
    if candidate is None or candidate not in trusted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed.",
            headers={"Cache-Control": "private, no-store"},
        )
