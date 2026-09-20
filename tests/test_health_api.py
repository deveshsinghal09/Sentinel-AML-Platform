from __future__ import annotations

import json

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import health


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(health.router)
    return app


def test_health_is_dependency_free_and_non_cacheable(monkeypatch):
    def unexpected_connection():
        raise AssertionError("liveness attempted a database connection")

    monkeypatch.setattr(health, "get_db_connection", unexpected_connection)

    with TestClient(_build_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "status": "ok",
        "service": "sentinel-aml-api",
        "version": "1.0.0",
        "environment": health.APP_ENV,
        "timestamp": response.json()["timestamp"],
    }
    assert response.json()["timestamp"].endswith("Z")


def test_readiness_returns_typed_503_when_database_is_missing(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(health, "DB_PATH", tmp_path / "missing.duckdb")

    with TestClient(_build_app()) as client:
        response = client.get("/ready")

    payload = response.json()
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert payload["status"] == "not_ready"
    assert payload["checks"]["database"]["status"] == "not_ready"
    assert payload["checks"]["transactions"]["status"] == "not_ready"
    assert payload["checks"]["saml_knowledge"]["status"] == "not_ready"


def test_readiness_requires_both_governed_tables(tmp_path, monkeypatch):
    database_path = tmp_path / "ready.duckdb"
    connection = duckdb.connect(str(database_path))
    connection.execute("CREATE TABLE transactions (id INTEGER)")
    connection.close()

    monkeypatch.setattr(health, "DB_PATH", database_path)
    monkeypatch.setattr(
        health,
        "get_db_connection",
        lambda: duckdb.connect(str(database_path)),
    )

    with TestClient(_build_app()) as client:
        incomplete = client.get("/ready")

    assert incomplete.status_code == 503
    assert incomplete.json()["checks"]["transactions"]["status"] == "ready"
    assert incomplete.json()["checks"]["saml_knowledge"]["status"] == "not_ready"

    connection = duckdb.connect(str(database_path))
    connection.execute("CREATE TABLE saml_knowledge (id INTEGER)")
    connection.close()

    with TestClient(_build_app()) as client:
        ready = client.get("/ready")

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert all(
        check["status"] == "ready"
        for check in ready.json()["checks"].values()
    )


def test_schema_catalog_is_inspectable_and_secret_free():
    with TestClient(_build_app()) as client:
        response = client.get("/schema")

    payload = response.json()
    serialized = json.dumps(payload).lower()
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    assert payload["service"] == "sentinel-aml-api"
    assert {"query_request", "agent_response"} == set(payload["schemas"])
    assert "query" in payload["schemas"]["query_request"]["properties"]
    assert "groq" not in serialized
    assert "api_key" not in serialized


def test_discovery_finds_health_router():
    from api.router_loader import discover_routers

    discovered = discover_routers()

    assert "api.routes.health" in {
        item.module_name for item in discovered
    }
