"""Reviewer-facing command-center summary assembled from governed stores."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class ActiveDatasetContext(BaseModel):
    """Minimal active evidence context displayed to an analyst."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    display_name: str
    dataset_type: Literal["primary", "knowledge", "kyc"]
    row_count: int = Field(ge=0)
    date_min: str | None = None
    date_max: str | None = None
    schema_version: str


class DashboardDatasetMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registered: int = Field(ge=0)
    active: int = Field(ge=0)
    governed_rows: int = Field(ge=0)
    active_primary: ActiveDatasetContext | None = None
    active_knowledge: ActiveDatasetContext | None = None


class DashboardWorkloadMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["available", "not_configured"]
    investigations: int = Field(default=0, ge=0)
    high_risk_entities: int = Field(default=0, ge=0)
    alerts: int = Field(default=0, ge=0)
    new: int = Field(default=0, ge=0)
    in_review: int = Field(default=0, ge=0)
    escalated: int = Field(default=0, ge=0)
    closed: int = Field(default=0, ge=0)


class DashboardSummary(BaseModel):
    """Stable, non-transactional read model for the analyst landing page."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    datasets: DashboardDatasetMetrics
    workload: DashboardWorkloadMetrics
    decision_notice: str


class DashboardRepository(Protocol):
    """Source boundary for the presentation-only command-center read model."""

    def list_datasets(self) -> list[Any]: ...

    def workflow_snapshot(self) -> dict[str, Any] | None: ...


class RuntimeDashboardRepository:
    """Late-bound integration with Devesh-owned persistence modules."""

    def list_datasets(self) -> list[Any]:
        from tools.dataset_store import list_datasets

        return list_datasets()

    def workflow_snapshot(self) -> dict[str, Any] | None:
        try:
            from tools.workflow_store import list_investigations, queue_summary
        except ModuleNotFoundError as exc:
            if exc.name != "tools.workflow_store":
                raise
            return None
        return {
            "queue": queue_summary(),
            "investigations": list_investigations(limit=100),
        }


def get_dashboard_repository() -> DashboardRepository:
    return RuntimeDashboardRepository()


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    raise TypeError("Dashboard repository returned an unsupported record")


def _active_context(
    datasets: list[dict[str, Any]],
    dataset_type: Literal["primary", "knowledge"],
) -> ActiveDatasetContext | None:
    selected = next(
        (
            item
            for item in datasets
            if item.get("dataset_type") == dataset_type
            and item.get("is_active") is True
        ),
        None,
    )
    if selected is None:
        return None
    return ActiveDatasetContext(
        dataset_id=selected["dataset_id"],
        display_name=selected["display_name"],
        dataset_type=selected["dataset_type"],
        row_count=selected.get("row_count", 0),
        date_min=selected.get("date_min"),
        date_max=selected.get("date_max"),
        schema_version=selected.get("schema_version", "1.0"),
    )


def _workload(snapshot: dict[str, Any] | None) -> DashboardWorkloadMetrics:
    if snapshot is None:
        return DashboardWorkloadMetrics(status="not_configured")

    queue = snapshot.get("queue") or {}
    investigations = [
        _payload(item) for item in snapshot.get("investigations") or []
    ]
    return DashboardWorkloadMetrics(
        status="available",
        investigations=len(investigations),
        high_risk_entities=sum(
            max(0, int(item.get("high_risk_count", 0)))
            for item in investigations
        ),
        alerts=max(0, int(queue.get("total", 0))),
        new=max(0, int(queue.get("new", 0))),
        in_review=max(0, int(queue.get("in_review", 0))),
        escalated=max(0, int(queue.get("escalated", 0))),
        closed=max(0, int(queue.get("closed", 0))),
    )


@router.get(
    "/summary",
    response_model=DashboardSummary,
    summary="Get the analyst command-center summary",
)
def dashboard_summary(
    response: Response,
    repository: DashboardRepository = Depends(get_dashboard_repository),
) -> DashboardSummary:
    """Build a bounded read model without loading raw transaction evidence."""

    response.headers["Cache-Control"] = "private, no-store"
    try:
        datasets = [_payload(item) for item in repository.list_datasets()]
        snapshot = repository.workflow_snapshot()
        return DashboardSummary(
            generated_at=datetime.now(timezone.utc).isoformat().replace(
                "+00:00",
                "Z",
            ),
            datasets=DashboardDatasetMetrics(
                registered=len(datasets),
                active=sum(item.get("is_active") is True for item in datasets),
                governed_rows=sum(
                    max(0, int(item.get("row_count", 0)))
                    for item in datasets
                ),
                active_primary=_active_context(datasets, "primary"),
                active_knowledge=_active_context(datasets, "knowledge"),
            ),
            workload=_workload(snapshot),
            decision_notice=(
                "Sentinel prioritizes evidence; a qualified analyst remains "
                "responsible for escalation and regulatory filing decisions."
            ),
        )
    except Exception as exc:
        logger.exception("Unable to build dashboard summary")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The command-center summary is temporarily unavailable.",
            headers={"Cache-Control": "private, no-store"},
        ) from exc
