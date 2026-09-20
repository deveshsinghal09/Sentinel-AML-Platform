from __future__ import annotations

from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import auth
from api.security.passwords import hash_password, verify_password
from api.security.sessions import SessionCookiePolicy
from api.services.auth_service import (
    AuthUser,
    AuthenticationService,
    UserCredential,
)


PASSWORD = "Correct horse battery staple!"


def _service(*, max_failures=5):
    return AuthenticationService(
        [
            UserCredential(
                user=AuthUser(
                    user_id="usr-analyst-1",
                    email="analyst@institution.test",
                    display_name="Avery Analyst",
                    roles=["analyst"],
                ),
                password_hash=hash_password(PASSWORD),
            )
        ],
        max_failures=max_failures,
        lockout_ttl=timedelta(minutes=5),
    )


def _client(service=None):
    app = FastAPI()
    app.include_router(auth.router)
    app.dependency_overrides[auth.get_authentication_service] = (
        lambda: service or _service()
    )
    app.dependency_overrides[auth.get_cookie_policy] = lambda: (
        SessionCookiePolicy(
            name="sentinel_session",
            secure=False,
            max_age_seconds=1_800,
        )
    )
    return TestClient(app)


def test_password_hash_is_salted_versioned_and_verifiable():
    first = hash_password(PASSWORD)
    second = hash_password(PASSWORD)

    assert first.startswith("pbkdf2_sha256$")
    assert first != second
    assert verify_password(PASSWORD, first)
    assert not verify_password("incorrect-password", first)
    assert not verify_password(PASSWORD, "malformed")


def test_login_session_and_logout_use_an_opaque_http_only_cookie():
    service = _service()
    with _client(service) as client:
        login = client.post(
            "/auth/login",
            json={
                "email": "  Analyst@Institution.Test ",
                "password": PASSWORD,
            },
        )
        session = client.get("/auth/session")
        logout = client.post("/auth/logout")
        rejected = client.get("/auth/session")

    assert login.status_code == 200
    assert login.headers["cache-control"] == "private, no-store"
    assert login.json()["user"] == {
        "user_id": "usr-analyst-1",
        "email": "analyst@institution.test",
        "display_name": "Avery Analyst",
        "roles": ["analyst"],
    }
    assert "token" not in login.json()
    cookie = login.headers["set-cookie"]
    assert "sentinel_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Max-Age=1800" in cookie
    assert session.status_code == 200
    assert logout.status_code == 204
    assert rejected.status_code == 401


def test_rejected_credentials_do_not_reveal_identity_state():
    with _client() as client:
        unknown = client.post(
            "/auth/login",
            json={
                "email": "unknown@institution.test",
                "password": "Incorrect password!",
            },
        )
        incorrect = client.post(
            "/auth/login",
            json={
                "email": "analyst@institution.test",
                "password": "Incorrect password!",
            },
        )

    assert unknown.status_code == incorrect.status_code == 401
    assert unknown.json() == incorrect.json() == {
        "detail": "The credentials were not accepted."
    }
    assert "set-cookie" not in unknown.headers


def test_repeated_failures_are_rate_limited_with_retry_guidance():
    with _client(_service(max_failures=2)) as client:
        first = client.post(
            "/auth/login",
            json={
                "email": "analyst@institution.test",
                "password": "Incorrect password!",
            },
        )
        second = client.post(
            "/auth/login",
            json={
                "email": "analyst@institution.test",
                "password": "Incorrect password!",
            },
        )
        locked = client.post(
            "/auth/login",
            json={
                "email": "analyst@institution.test",
                "password": PASSWORD,
            },
        )

    assert first.status_code == 401
    assert second.status_code == locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0
    assert "password" not in locked.text.lower()


def test_forwarding_headers_cannot_bypass_login_rate_limits():
    with _client(_service(max_failures=2)) as client:
        first = client.post(
            "/auth/login",
            headers={"X-Forwarded-For": "198.51.100.10"},
            json={
                "email": "analyst@institution.test",
                "password": "Incorrect password!",
            },
        )
        second = client.post(
            "/auth/login",
            headers={"X-Forwarded-For": "198.51.100.11"},
            json={
                "email": "analyst@institution.test",
                "password": "Incorrect password!",
            },
        )

    assert first.status_code == 401
    assert second.status_code == 429


def test_cross_site_login_is_rejected_before_credentials_are_checked():
    with _client() as client:
        response = client.post(
            "/auth/login",
            headers={"Origin": "https://attacker.example"},
            json={
                "email": "analyst@institution.test",
                "password": PASSWORD,
            },
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Request origin is not allowed."}
    assert "set-cookie" not in response.headers


def test_login_contract_rejects_extra_and_malformed_fields():
    with _client() as client:
        malformed = client.post(
            "/auth/login",
            json={
                "email": "not-an-email",
                "password": PASSWORD,
                "role": "compliance_admin",
            },
        )

    assert malformed.status_code == 422
