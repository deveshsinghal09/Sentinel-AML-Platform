"""Read-only presentation routes for governed dataset workspaces."""
from __future__ import annotations

import logging
import re
from typing import Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field


logger = logging.getLogger(__name__)

DatasetType = Literal["primary", "knowledge", "kyc"]
_DATASET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")

router = APIRouter(prefix="/datasets", tags=["datasets"])


class DatasetView(BaseModel):
    """Reviewer-safe metadata for one isolated dataset workspace."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    display_name: str
    source_file: str | None = None
    dataset_type: DatasetType
    file_size_bytes: int = Field(default=0, ge=0)
    row_count: int = Field(default=0, ge=0)
    laundering_count: int = Field(default=0, ge=0)
    laundering_rate: float = Field(default=0.0, ge=0, le=1)
    date_min: str | None = None
    date_max: str | None = None
    schema_version: str = "1.0"
    md5_fingerprint: str | None = None
    ingested_at: str
    is_active: bool = False
    notes: str = ""
    column_map: dict[str, str] = Field(default_factory=dict)
    schema_detected: str = ""


class DatasetCatalogSummary(BaseModel):
    """Compact governance metrics used by dataset and command-center views."""

    model_config = ConfigDict(extra="forbid")

    registered: int = Field(ge=0)
    active: int = Field(ge=0)
    primary: int = Field(ge=0)
    knowledge: int = Field(ge=0)
    kyc: int = Field(ge=0)
    governed_rows: int = Field(ge=0)
    labelled_laundering_rows: int = Field(ge=0)


class DatasetRepository(Protocol):
    """Minimal data-store surface consumed by presentation routes."""

    def list_datasets(self) -> list[Any]: ...

    def get_dataset(self, dataset_id: str) -> Any | None: ...


class RuntimeDatasetRepository:
    """Late-bound adapter to Devesh's governed dataset store."""

    def list_datasets(self) -> list[Any]:
        from tools.dataset_store import list_datasets

        return list_datasets()

    def get_dataset(self, dataset_id: str) -> Any | None:
        from tools.dataset_store import get_dataset

        return get_dataset(dataset_id)


def get_dataset_repository() -> DatasetRepository:
    """FastAPI dependency kept replaceable for tests and future persistence."""

    return RuntimeDatasetRepository()


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    raise TypeError("Dataset repository returned an unsupported record")


def _view(value: Any) -> DatasetView:
    payload = _payload(value)
    source_file = payload.get("source_file")
    if source_file:
        payload["source_file"] = str(source_file).replace("\\", "/").rsplit("/", 1)[-1]
    return DatasetView.model_validate(payload)


def _load_catalog(repository: DatasetRepository) -> list[DatasetView]:
    try:
        return [_view(item) for item in repository.list_datasets()]
    except Exception as exc:
        logger.exception("Unable to load governed dataset catalog")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The governed dataset catalog is temporarily unavailable.",
            headers={"Cache-Control": "private, no-store"},
        ) from exc


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


@router.get(
    "",
    response_model=list[DatasetView],
    summary="List governed dataset workspaces",
)
def list_registered_datasets(
    response: Response,
    dataset_type: DatasetType | None = Query(default=None),
    active_only: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repository: DatasetRepository = Depends(get_dataset_repository),
) -> list[DatasetView]:
    """Return filtered metadata only; raw transaction records are never exposed."""

    _no_store(response)
    datasets = _load_catalog(repository)
    if dataset_type is not None:
        datasets = [item for item in datasets if item.dataset_type == dataset_type]
    if active_only is not None:
        datasets = [item for item in datasets if item.is_active is active_only]
    return datasets[offset : offset + limit]


@router.get(
    "/summary",
    response_model=DatasetCatalogSummary,
    summary="Summarize the governed dataset catalog",
)
def dataset_catalog_summary(
    response: Response,
    repository: DatasetRepository = Depends(get_dataset_repository),
) -> DatasetCatalogSummary:
    """Return aggregate governance metrics without inspecting transaction rows."""

    _no_store(response)
    datasets = _load_catalog(repository)
    counts = {
        dataset_type: sum(
            item.dataset_type == dataset_type for item in datasets
        )
        for dataset_type in ("primary", "knowledge", "kyc")
    }
    return DatasetCatalogSummary(
        registered=len(datasets),
        active=sum(item.is_active for item in datasets),
        primary=counts["primary"],
        knowledge=counts["knowledge"],
        kyc=counts["kyc"],
        governed_rows=sum(item.row_count for item in datasets),
        labelled_laundering_rows=sum(
            item.laundering_count for item in datasets
        ),
    )


@router.get(
    "/{dataset_id}",
    response_model=DatasetView,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Dataset not found"}},
    summary="Get one governed dataset workspace",
)
def dataset_detail(
    response: Response,
    dataset_id: str = Path(
        min_length=1,
        max_length=80,
        pattern=_DATASET_ID.pattern,
    ),
    repository: DatasetRepository = Depends(get_dataset_repository),
) -> DatasetView:
    """Return one exact metadata record using an identifier-safe lookup."""

    _no_store(response)
    try:
        dataset = repository.get_dataset(dataset_id)
        if dataset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found.",
                headers={"Cache-Control": "private, no-store"},
            )
        return _view(dataset)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unable to load governed dataset metadata")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dataset metadata is temporarily unavailable.",
            headers={"Cache-Control": "private, no-store"},
        ) from exc
