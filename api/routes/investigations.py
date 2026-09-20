"""Read-only presentation routes for persisted AML investigations."""
from __future__ import annotations

import logging
import re
from typing import Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field


logger = logging.getLogger(__name__)

InvestigationStatus = Literal["open", "in_review", "escalated", "closed"]
_INVESTIGATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")

router = APIRouter(prefix="/investigations", tags=["investigations"])


class InvestigationListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investigation_id: str
    dataset_id: str | None = None
    dataset_name: str | None = None
    query: str
    intent: str
    pattern_type: str | None = None
    status: InvestigationStatus
    disposition: str | None = None
    flagged_count: int = Field(default=0, ge=0)
    high_risk_count: int = Field(default=0, ge=0)
    alert_count: int = Field(default=0, ge=0)
    created_at: str
    updated_at: str


class InvestigationDetail(InvestigationListItem):
    response: dict[str, Any]


class InvestigationStatusSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    open: int = Field(ge=0)
    in_review: int = Field(ge=0)
    escalated: int = Field(ge=0)
    closed: int = Field(ge=0)
    high_risk_entities: int = Field(ge=0)
    alerts: int = Field(ge=0)


class InvestigationRepository(Protocol):
    def list_investigations(
        self,
        *,
        limit: int,
        dataset_id: str | None,
    ) -> list[Any]: ...

    def get_investigation(self, investigation_id: str) -> Any | None: ...


class RuntimeInvestigationRepository:
    def list_investigations(
        self,
        *,
        limit: int,
        dataset_id: str | None,
    ) -> list[Any]:
        from tools.workflow_store import list_investigations

        return list_investigations(limit=limit, dataset_id=dataset_id)

    def get_investigation(self, investigation_id: str) -> Any | None:
        from tools.workflow_store import get_investigation

        return get_investigation(investigation_id)


def get_investigation_repository() -> InvestigationRepository:
    return RuntimeInvestigationRepository()


def record_payload(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return dict(record)
    if hasattr(record, "model_dump"):
        return record.model_dump(mode="json")
    raise TypeError("Investigation store returned an unsupported record")


def _list_item(record: Any) -> InvestigationListItem:
    payload = record_payload(record)
    payload.pop("response", None)
    return InvestigationListItem.model_validate(payload)


def _detail(record: Any) -> InvestigationDetail:
    return InvestigationDetail.model_validate(record_payload(record))


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _unavailable(exc: Exception) -> HTTPException:
    logger.exception("Investigation presentation store failed")
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Investigation history is temporarily unavailable.",
        headers={"Cache-Control": "private, no-store"},
    )


def _load_items(
    repository: InvestigationRepository,
    *,
    dataset_id: str | None = None,
) -> list[InvestigationListItem]:
    try:
        return [
            _list_item(record)
            for record in repository.list_investigations(
                limit=500,
                dataset_id=dataset_id,
            )
        ]
    except Exception as exc:
        raise _unavailable(exc) from exc


@router.get(
    "",
    response_model=list[InvestigationListItem],
    summary="List persisted AML investigations",
)
def list_investigation_history(
    response: Response,
    dataset_id: str | None = Query(default=None, max_length=80),
    workflow_status: InvestigationStatus | None = Query(default=None),
    pattern_type: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repository: InvestigationRepository = Depends(
        get_investigation_repository
    ),
) -> list[InvestigationListItem]:
    _no_store(response)
    records = _load_items(repository, dataset_id=dataset_id)
    if workflow_status is not None:
        records = [
            record for record in records if record.status == workflow_status
        ]
    if pattern_type:
        selected_pattern = pattern_type.strip().casefold()
        records = [
            record
            for record in records
            if (record.pattern_type or "").casefold() == selected_pattern
        ]
    return records[offset : offset + limit]


@router.get(
    "/summary",
    response_model=InvestigationStatusSummary,
    summary="Summarize investigation workload",
)
def investigation_status_summary(
    response: Response,
    dataset_id: str | None = Query(default=None, max_length=80),
    repository: InvestigationRepository = Depends(
        get_investigation_repository
    ),
) -> InvestigationStatusSummary:
    _no_store(response)
    records = _load_items(repository, dataset_id=dataset_id)
    return InvestigationStatusSummary(
        total=len(records),
        open=sum(record.status == "open" for record in records),
        in_review=sum(record.status == "in_review" for record in records),
        escalated=sum(record.status == "escalated" for record in records),
        closed=sum(record.status == "closed" for record in records),
        high_risk_entities=sum(record.high_risk_count for record in records),
        alerts=sum(record.alert_count for record in records),
    )


@router.get(
    "/{investigation_id}",
    response_model=InvestigationDetail,
    summary="Get one persisted AML investigation",
)
def investigation_detail(
    response: Response,
    investigation_id: str = Path(
        min_length=1,
        max_length=80,
        pattern=_INVESTIGATION_ID.pattern,
    ),
    repository: InvestigationRepository = Depends(
        get_investigation_repository
    ),
) -> InvestigationDetail:
    _no_store(response)
    try:
        record = repository.get_investigation(investigation_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Investigation not found.",
                headers={"Cache-Control": "private, no-store"},
            )
        return _detail(record)
    except HTTPException:
        raise
    except Exception as exc:
        raise _unavailable(exc) from exc
