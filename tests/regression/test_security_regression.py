from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.security import origin, sessions
from api.security.origin import enforce_trusted_origin
from api.security.passwords import hash_password, verify_password


def test_password_hash_never_contains_plaintext_and_rejects_tampering():
    encoded = hash_password(
        "Correct-Horse-Battery-Staple",
        salt=b"0123456789abcdef",
    )

    assert "Correct-Horse" not in encoded
    assert verify_password("Correct-Horse-Battery-Staple", encoded)
    assert not verify_password("wrong-password", encoded)
    assert not verify_password(
        "Correct-Horse-Battery-Staple",
        encoded[:-1] + ("A" if encoded[-1] != "A" else "B"),
    )
    assert not verify_password("anything", "pbkdf2_sha256$1$bad$bad")


def test_browser_mutation_rejects_cross_origin_and_accepts_trusted_origin(monkeypatch):
    monkeypatch.setattr(origin, "ALLOWED_ORIGINS", ("https://aml.bank.test",))
    app = FastAPI()

    @app.post("/mutation", dependencies=[Depends(enforce_trusted_origin)])
    def mutation():
        return {"ok": True}

    with TestClient(app) as client:
        trusted = client.post(
            "/mutation",
            headers={"Origin": "https://aml.bank.test"},
        )
        hostile = client.post(
            "/mutation",
            headers={"Origin": "https://evil.test"},
        )

    assert trusted.status_code == 200
    assert hostile.status_code == 403
    assert hostile.headers["cache-control"] == "private, no-store"


def test_production_cookie_is_host_only_secure_and_strict(monkeypatch):
    monkeypatch.setattr(sessions, "APP_ENV", "production")
    monkeypatch.delenv("SENTINEL_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("SENTINEL_SESSION_IDLE_MINUTES", "30")

    policy = sessions.get_session_cookie_policy()

    assert policy.name == "__Host-sentinel_session"
    assert policy.secure
    assert policy.path == "/"
    assert policy.same_site == "strict"
    assert policy.max_age_seconds == 1_800
