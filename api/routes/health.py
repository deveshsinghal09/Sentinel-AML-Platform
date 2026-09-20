"""Operational liveness, readiness, and public schema contracts."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Response, status

from agent.models import (
    AgentResponse,
    HealthResponse,
    QueryRequest,
    ReadinessCheck,
    ReadinessResponse,
    SchemaCatalogResponse,
)
from config import APP_ENV, DB_PATH
from tools.data_loader import (
    _SAML_TABLE_NAME,
    _table_exists,
    get_db_connection,
)


SERVICE_NAME = "sentinel-aml-api"
SERVICE_VERSION = "1.0.0"

router = APIRouter(tags=["operations"])


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _not_ready_checks(detail: str) -> dict[str, ReadinessCheck]:
    return {
        "database": ReadinessCheck(status="not_ready", detail=detail),
        "transactions": ReadinessCheck(
            status="not_ready",
            detail="Governed transaction table was not inspected",
        ),
        "saml_knowledge": ReadinessCheck(
            status="not_ready",
            detail="AML typology knowledge table was not inspected",
        ),
    }


def inspect_readiness() -> ReadinessResponse:
    """Inspect required local dependencies without creating missing state."""
    if not DB_PATH.is_file():
        return ReadinessResponse(
            status="not_ready",
            service=SERVICE_NAME,
            version=SERVICE_VERSION,
            timestamp=_timestamp(),
            checks=_not_ready_checks("Analytical database is unavailable"),
        )

    try:
        connection = get_db_connection()
    except Exception:
        return ReadinessResponse(
            status="not_ready",
            service=SERVICE_NAME,
            version=SERVICE_VERSION,
            timestamp=_timestamp(),
            checks=_not_ready_checks("Analytical database could not be opened"),
        )

    try:
        transactions_ready = _table_exists(connection)
        knowledge_ready = _table_exists(connection, _SAML_TABLE_NAME)
    except Exception:
        return ReadinessResponse(
            status="not_ready",
            service=SERVICE_NAME,
            version=SERVICE_VERSION,
            timestamp=_timestamp(),
            checks=_not_ready_checks("Analytical database inspection failed"),
        )
    finally:
        connection.close()

    checks = {
        "database": ReadinessCheck(
            status="ready",
            detail="DuckDB connection and metadata inspection succeeded",
        ),
        "transactions": ReadinessCheck(
            status="ready" if transactions_ready else "not_ready",
            detail=(
                "Governed transaction table is available"
                if transactions_ready
                else "Governed transaction table is unavailable"
            ),
        ),
        "saml_knowledge": ReadinessCheck(
            status="ready" if knowledge_ready else "not_ready",
            detail=(
                "AML typology knowledge table is available"
                if knowledge_ready
                else "AML typology knowledge table is unavailable"
            ),
        ),
    }
    ready = transactions_ready and knowledge_ready
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        timestamp=_timestamp(),
        checks=checks,
    )


@router.get("/health", response_model=HealthResponse, summary="Service liveness")
def health(response: Response) -> HealthResponse:
    """Return process liveness without touching data or external services."""
    response.headers["Cache-Control"] = "no-store"
    return HealthResponse(
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        environment=APP_ENV,
        timestamp=_timestamp(),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ReadinessResponse,
            "description": "A required governed dependency is unavailable",
        }
    },
    summary="Service readiness",
)
def readiness(response: Response) -> ReadinessResponse:
    """Return readiness for the governed transaction and knowledge stores."""
    response.headers["Cache-Control"] = "no-store"
    snapshot = inspect_readiness()
    if snapshot.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return snapshot


@router.get(
    "/schema",
    response_model=SchemaCatalogResponse,
    summary="Public agent contract schemas",
)
def schema_catalog(response: Response) -> SchemaCatalogResponse:
    """Expose versioned client contracts without runtime configuration."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return SchemaCatalogResponse(
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        schemas={
            "query_request": QueryRequest.model_json_schema(),
            "agent_response": AgentResponse.model_json_schema(),
        },
    )
