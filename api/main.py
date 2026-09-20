"""FastAPI application for the AML agent."""
from __future__ import annotations

import sys
import hashlib
import html
import io
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zipfile import BadZipFile

from fastapi import FastAPI, File, Form, HTTPException, Query as ApiQuery, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.models import (
    AgentResponse,
    AlertQueueItem,
    AuditEvent,
    CustomerDetail,
    DatasetInfo,
    DatasetSwitchResult,
    DatasetUploadResult,
    InvestigationRecord,
    InvestigationSummary,
    QueryRequest,
    QueueAssignmentRequest,
    QueueDispositionRequest,
    QueueNoteRequest,
)
from agent.runner import AgentRunner
from config import (
    ALLOWED_ORIGINS,
    API_HOST,
    API_PORT,
    CSV_PATH,
    DB_PATH,
    LOG_LEVEL,
    SAML_D_PATH,
    MAX_UPLOAD_BYTES,
    UPLOAD_DIR,
)

logger.remove()
from api.services.aws.settings import enabled as aws_enabled
logger.add(sys.stderr, level=LOG_LEVEL.upper(), serialize=aws_enabled(),
           diagnose=False, backtrace=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize persisted data, knowledge retrieval, and the runner."""
    logger.info("AML Agent API starting")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not DB_PATH.exists():
        if not CSV_PATH.exists():
            logger.warning("HI-Small CSV not found at {}", CSV_PATH)
        elif not SAML_D_PATH.exists():
            logger.warning("SAML-D CSV not found at {}", SAML_D_PATH)
        else:
            from tools.data_loader import ingest_csv, ingest_saml_knowledge

            try:
                ingest_csv()
                ingest_saml_knowledge()
            except Exception as exc:
                logger.warning("Startup ingest failed (non-fatal): {}", exc)

    try:
        from agent.knowledge import get_knowledge

        get_knowledge()
    except Exception as exc:
        logger.warning("Knowledge index failed (non-fatal): {}", exc)

    try:
        from tools.workflow_store import initialize_workflow_schema

        initialize_workflow_schema()
    except Exception as exc:
        logger.warning("Workflow schema initialization failed: {}", exc)

    try:
        from tools.dataset_store import initialize_dataset_registry

        initialize_dataset_registry()
    except Exception as exc:
        logger.warning("Dataset registry initialization failed: {}", exc)

    app.state.agent_runner = AgentRunner()
    app.state.workflow_enabled = True
    yield
    logger.info("AML Agent API shutting down")


app = FastAPI(
    title="AML Suspicious Activity Detection Agent",
    description=(
        "Dynamic AML query planning over HI-Small, grounded by the separate "
        "SAML-D knowledge and validation dataset."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

if aws_enabled():
    from api.services.aws.errors import install_exception_handlers
    install_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Content-Disposition"],
)


@app.middleware("http")
async def log_request(request: Request, call_next):
    from time import perf_counter
    from api.services.aws.logging import event
    started = perf_counter()
    request_id = uuid4().hex
    try:
        response = await call_next(request)
        event("api_request", request_id=request_id, method=request.method,
              status_code=response.status_code,
              duration_ms=round((perf_counter() - started) * 1000, 2))
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        event("api_request_failed", request_id=request_id, error_type=type(exc).__name__)
        raise


def _download(content: bytes, media_type: str, filename: str, *, s3_key: str | None = None) -> StreamingResponse:
    safe_name = "".join(
        character for character in filename
        if character.isalnum() or character in {"-", "_", "."}
    )
    if aws_enabled():
        from api.services.aws.artifacts import archive_export
        try:
            archive_export(content, safe_name, media_type, key=s3_key)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Export storage unavailable; retry later") from exc
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


def _load_investigation_or_latest(
    investigation_id: str | None,
) -> InvestigationRecord:
    from tools.workflow_store import get_investigation, list_investigations

    resolved = investigation_id
    if not resolved:
        recent = list_investigations(limit=1)
        resolved = recent[0].investigation_id if recent else None
    record = get_investigation(resolved) if resolved else None
    if record is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return record


async def _store_upload(
    upload: UploadFile,
    *,
    persist: bool = True,
) -> tuple[Path, int, str]:
    filename = Path(upload.filename or "upload.csv").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise HTTPException(
            status_code=415,
            detail="Only CSV and Excel (.xlsx) uploads are supported",
        )
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    temporary = UPLOAD_DIR / f".upload-{uuid4().hex}{suffix}"
    size = 0
    digest = hashlib.md5()
    try:
        with temporary.open("wb") as destination:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds size limit")
                digest.update(chunk)
                destination.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="Upload is empty")
        fingerprint = digest.hexdigest()
        if not persist:
            return temporary, size, fingerprint
        stored = UPLOAD_DIR / f"{fingerprint}{suffix}"
        if stored.exists():
            temporary.unlink()
        else:
            temporary.replace(stored)
        return stored, size, fingerprint
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    finally:
        await upload.close()


@app.get("/health", tags=["ops"])
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok", "phase": "C-advanced-quality"}


@app.get("/ready", tags=["ops"])
def ready() -> dict:
    """Readiness probe that verifies both governed analytical tables."""
    from tools.data_loader import _SAML_TABLE_NAME, _table_exists, get_db_connection

    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Analytical database unavailable")
    conn = get_db_connection()
    try:
        transactions_ready = _table_exists(conn)
        knowledge_ready = _table_exists(conn, _SAML_TABLE_NAME)
    finally:
        conn.close()
    if not transactions_ready or not knowledge_ready:
        raise HTTPException(
            status_code=503,
            detail="Required analytical tables are unavailable",
        )
    return {
        "status": "ready",
        "transactions": True,
        "saml_knowledge": True,
    }


@app.post("/ingest", tags=["ops"])
async def ingest(force: bool = False) -> dict:
    """Ingest both datasets while preserving separate DuckDB tables."""
    from tools.data_loader import ingest_csv, ingest_saml_knowledge

    try:
        if aws_enabled():
            from api.services.aws.bootstrap import ingest_baselines
            return ingest_baselines(force=force)
        transactions = ingest_csv(force=force)
        saml_knowledge = ingest_saml_knowledge(force=force)
        return {
            "status": "ok",
            "transactions": transactions,
            "saml_knowledge": saml_knowledge,
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/stats", tags=["data"])
async def dataset_stats() -> dict:
    """Return high-level statistics for both persisted tables."""
    from tools.data_loader import (
        _SAML_TABLE_NAME,
        _table_exists,
        get_db_connection,
        get_saml_summary_stats,
        get_summary_stats,
    )
    from tools.dataset_store import active_dataset

    conn = get_db_connection()
    try:
        if not _table_exists(conn):
            raise HTTPException(
                status_code=404,
                detail="Transactions table not found. Call POST /ingest first.",
            )
        selected = active_dataset("primary", conn=conn)
        primary = get_summary_stats(
            conn=conn,
            dataset_id=selected.dataset_id if selected else None,
        )
        saml = (
            get_saml_summary_stats(conn=conn)
            if _table_exists(conn, _SAML_TABLE_NAME)
            else None
        )
    finally:
        conn.close()

    for key in ("date_min", "date_max"):
        if primary.get(key) is not None:
            primary[key] = str(primary[key])
    return {"transactions": primary, "saml_knowledge": saml}


@app.get("/model-card", tags=["ml"])
def model_card() -> dict:
    """Return truthful, reproducible metadata for the active anomaly model."""
    import sklearn

    from tools.ml_engine import (
        CONTAMINATION,
        FEATURES,
        RANDOM_STATE,
        get_model_bundle,
    )

    bundle = get_model_bundle()
    return {
        "model_id": "sentinel-saml-iforest-v1",
        "model_type": "Isolation Forest",
        "library": "scikit-learn",
        "library_version": sklearn.__version__,
        "algorithm": "iForest",
        "training_dataset": "SAML-D normal-behaviour sample",
        "training_rows": bundle.training_rows,
        "contamination_rate": CONTAMINATION,
        "random_state": RANDOM_STATE,
        "n_estimators": int(bundle.model.n_estimators),
        "features": FEATURES,
        "feature_count": len(FEATURES),
        "score_range": {
            "raw_min": bundle.raw_min,
            "raw_max": bundle.raw_max,
        },
        "decision_rule": "IsolationForest.predict(feature_vector) == -1",
        "normalization": "min-max over the training anomaly-score range",
        "status": "validated_demo",
        "drift_status": "monitored_via_psi",
        "limitations": [
            "Trained on a SAML-D normal sample, not HI-Small positive labels.",
            "The static contamination rate may not match a bank's alert appetite.",
            "No online learning or feature-drift monitoring is implemented.",
            "The risk score is decision support and requires analyst review.",
        ],
        "grounding": "SAML-D knowledge and validation table",
    }


@app.get("/model-card/drift", tags=["ml"])
def model_drift(
    limit: int = ApiQuery(default=1_000, ge=100, le=10_000),
) -> dict:
    """Compare the current HI-Small batch to the model's training baseline."""
    from tools.data_loader import load
    from tools.model_drift import compute_drift_report

    current = load(limit=limit)
    report = compute_drift_report(current)
    report["current_dataset"] = "HI-Small active investigation slice"
    report["baseline_dataset"] = "SAML-D normal-behaviour training sample"
    return report


@app.get(
    "/investigations",
    response_model=list[InvestigationSummary],
    tags=["workflow"],
)
def investigations(
    limit: int = ApiQuery(default=50, ge=1, le=200),
    dataset_id: str | None = ApiQuery(default=None, max_length=80),
) -> list[InvestigationSummary]:
    from tools.workflow_store import list_investigations

    return list_investigations(limit=limit, dataset_id=dataset_id)


@app.get(
    "/investigations/{investigation_id}",
    response_model=InvestigationRecord,
    tags=["workflow"],
)
def investigation_detail(investigation_id: str) -> InvestigationRecord:
    from tools.workflow_store import get_investigation

    record = get_investigation(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return record


@app.get("/investigations/{investigation_id}/aws-status", tags=["workflow"])
def investigation_aws_status(investigation_id: str) -> dict:
    """Expose real publish status and a short-lived private report download."""
    if not aws_enabled():
        return {"aws_enabled": False}
    from api.services.aws.dynamodb_service import InvestigationRepository
    from api.services.aws.s3_service import S3Service
    item = InvestigationRepository().get_investigation(investigation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    key = item.get("report_s3_key")
    return {"aws_enabled": True, "notification_status": item.get("notification_status"),
            "report_url": S3Service().generate_presigned_url(key) if key else None}


@app.post("/investigations/{investigation_id}/retry-aws", tags=["workflow"])
def retry_investigation_aws(investigation_id: str) -> dict:
    if not aws_enabled():
        raise HTTPException(status_code=409, detail="AWS mode is disabled")
    from api.services.aws.completion import complete
    record = _load_investigation_or_latest(investigation_id)
    try:
        complete(record.response)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Report storage unavailable; retry later") from exc
    return investigation_aws_status(investigation_id)


@app.get("/queue/summary", tags=["workflow"])
def review_queue_summary() -> dict[str, int]:
    from tools.workflow_store import queue_summary

    return queue_summary()


@app.get("/queue", tags=["workflow"])
def review_queue(
    status: str | None = ApiQuery(default=None),
    limit: int = ApiQuery(default=100, ge=1, le=500),
) -> dict:
    from tools.workflow_store import list_queue, queue_summary

    allowed = {"new", "in_review", "escalated", "closed"}
    if status is not None and status not in allowed:
        raise HTTPException(status_code=422, detail="Unsupported queue status")
    items = list_queue(status=status, limit=limit)
    summary = queue_summary()
    return {
        "items": [item.model_dump() for item in items],
        "returned": len(items),
        "summary": summary,
    }


@app.post(
    "/queue/{alert_id}/assign",
    response_model=AlertQueueItem,
    tags=["workflow"],
)
def assign_queue_item(
    alert_id: str,
    request: QueueAssignmentRequest,
) -> AlertQueueItem:
    from tools.workflow_store import assign_alert

    item = assign_alert(alert_id, request.assigned_to, request.actor)
    if item is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return item


@app.post(
    "/queue/{alert_id}/disposition",
    response_model=AlertQueueItem,
    tags=["workflow"],
)
def disposition_queue_item(
    alert_id: str,
    request: QueueDispositionRequest,
) -> AlertQueueItem:
    from tools.workflow_store import disposition_alert

    item = disposition_alert(alert_id, request.disposition, request.actor)
    if item is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return item


@app.post(
    "/queue/{alert_id}/notes",
    response_model=AlertQueueItem,
    tags=["workflow"],
)
def note_queue_item(
    alert_id: str,
    request: QueueNoteRequest,
) -> AlertQueueItem:
    from tools.workflow_store import append_alert_note

    item = append_alert_note(alert_id, request.note, request.actor)
    if item is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return item


@app.get("/audit", tags=["governance"])
def audit_trail(
    limit: int = ApiQuery(default=100, ge=1, le=500),
    offset: int = ApiQuery(default=0, ge=0),
    event_type: str | None = ApiQuery(default=None),
) -> dict:
    """Read immutable audit records; external audit insertion is prohibited."""
    from tools.workflow_store import list_audit_events

    events, total = list_audit_events(
        limit=limit,
        offset=offset,
        event_type=event_type,
    )
    return {
        "items": [event.model_dump() for event in events],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/policy", tags=["governance"])
def policy() -> dict:
    """Return the effective read-only risk policy used by the engines."""
    from config import RISK_HIGH_THRESHOLD, RISK_LOW_THRESHOLD
    from tools.escalation import MONITOR_MAX_SCORE, REVIEW_MAX_SCORE
    from tools.risk_scorer import (
        BASE_WEIGHTS,
        HIGH_RISK_COUNTRIES,
        HIGH_RISK_COUNTRY_BOOST,
    )
    from tools.rule_engine import (
        STRUCTURING_LOWER_BOUND,
        STRUCTURING_MIN_COUNT,
        STRUCTURING_THRESHOLD,
        STRUCTURING_WINDOW_DAYS,
    )
    from tools.workflow_store import RISK_POLICY_VERSION

    return {
        "version": RISK_POLICY_VERSION,
        "effective_date": "2026-07-26",
        "approved_by": "Sentinel demo policy owner",
        "jurisdiction": "US BSA/FinCEN demonstration baseline",
        "currency": "USD-equivalent",
        "mode": "read_only",
        "thresholds": {
            "risk_low": RISK_LOW_THRESHOLD,
            "risk_high": RISK_HIGH_THRESHOLD,
            "escalation_review": MONITOR_MAX_SCORE,
            "escalation_report": REVIEW_MAX_SCORE,
            "structuring_upper": STRUCTURING_THRESHOLD,
            "structuring_lower": STRUCTURING_LOWER_BOUND,
            "structuring_min_transactions": STRUCTURING_MIN_COUNT,
            "structuring_window_days": STRUCTURING_WINDOW_DAYS,
            "country_risk_boost": HIGH_RISK_COUNTRY_BOOST,
        },
        "risk_weights": BASE_WEIGHTS,
        "high_risk_countries": sorted(HIGH_RISK_COUNTRIES),
        "change_history": [],
        "limitations": [
            "Demonstration policy; institution and jurisdiction calibration is required.",
            "Policy writes require maker-checker approval and are not exposed in Phase B.",
        ],
    }


@app.get("/datasets", response_model=list[DatasetInfo], tags=["data"])
def datasets() -> list[DatasetInfo]:
    """Return every governed dataset workspace."""
    from tools.dataset_store import list_datasets

    return list_datasets()


@app.post("/datasets/inspect", tags=["data"])
async def inspect_dataset(file: UploadFile = File(...)) -> dict:
    """Inspect an upload without registering or activating it."""
    from tools.importer import inspect_upload

    path, _, _ = await _store_upload(file, persist=False)
    try:
        inspection = inspect_upload(path)
        return {
            "schema_detected": inspection.schema_name,
            "column_map": inspection.column_map,
            "columns": inspection.columns,
            "preview": inspection.preview,
            "warnings": inspection.warnings,
        }
    except (ValueError, BadZipFile) as exc:
        raise HTTPException(status_code=422, detail="Invalid dataset file: " + str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)


@app.post(
    "/datasets/upload",
    response_model=DatasetUploadResult,
    tags=["data"],
)
async def upload_dataset(
    file: UploadFile = File(...),
    display_name: str = Form(default=""),
    dataset_type: Literal["primary", "knowledge", "kyc"] = Form(default="primary"),
    force: bool = Form(default=False),
) -> DatasetUploadResult:
    """Validate and ingest an upload into an isolated DuckDB schema."""
    from tools.dataset_store import register_uploaded_dataset

    original_name = Path(file.filename or "dataset").stem
    original_filename = Path(file.filename or "dataset.csv").name
    name = (display_name.strip() or original_name)[:120]
    path, size, fingerprint = await _store_upload(file)
    try:
        from tools.dataset_store import get_dataset
        existing = get_dataset(f"ds_{fingerprint[:12]}") if aws_enabled() else None
        # AWS retries may arrive after ingestion committed but the upload failed.
        if existing and not force:
            if existing.md5_fingerprint != fingerprint or existing.dataset_type != dataset_type:
                raise ValueError("Dataset already registered with conflicting metadata")
            result = DatasetUploadResult(dataset_id=existing.dataset_id,
                display_name=existing.display_name, row_count=existing.row_count,
                schema_detected=existing.schema_detected, warnings=["Existing dataset reused"])
        else:
            result = register_uploaded_dataset(
                path=path,
                display_name=name,
                dataset_type=dataset_type,
                md5_fingerprint=fingerprint,
                file_size_bytes=size,
                source_file=original_filename,
                force=force,
            )
        from api.services.aws.settings import enabled
        if enabled():
            from api.services.aws.datasets import upload_dataset as store_cloud_dataset
            store_cloud_dataset(path, result.dataset_id, original_filename, dataset_type, fingerprint)
        from tools.workflow_store import record_audit_event

        record_audit_event(
            event_type="dataset_uploaded",
            actor="demo.analyst",
            payload={
                "dataset_id": result.dataset_id,
                "display_name": result.display_name,
                "dataset_type": dataset_type,
                "row_count": result.row_count,
                "md5_fingerprint": fingerprint,
            },
        )
        return result
    except (ValueError, BadZipFile) as exc:
        status = 409 if "already registered" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except Exception as exc:
        if aws_enabled():
            raise HTTPException(status_code=503, detail="Dataset storage unavailable. Retry this upload.") from exc
        raise
    finally:
        from api.services.aws.settings import enabled
        if enabled():
            path.unlink(missing_ok=True)


@app.get("/datasets/{dataset_id}", response_model=DatasetInfo, tags=["data"])
def dataset_detail(dataset_id: str) -> DatasetInfo:
    from tools.dataset_store import get_dataset

    dataset = get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


@app.post(
    "/datasets/{dataset_id}/activate",
    response_model=DatasetSwitchResult,
    tags=["data"],
)
def activate_registered_dataset(dataset_id: str) -> DatasetSwitchResult:
    from tools.dataset_store import activate_dataset

    try:
        result = activate_dataset(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    from tools.ml_engine import clear_model_cache

    clear_model_cache()
    from tools.workflow_store import record_audit_event

    record_audit_event(
        event_type="dataset_activated",
        actor="demo.analyst",
        payload={
            "dataset_id": result.active_dataset_id,
            "previous_dataset_id": result.previous_dataset_id,
        },
    )
    return result


@app.delete("/datasets/{dataset_id}", tags=["data"])
def delete_registered_dataset(dataset_id: str) -> dict[str, str]:
    from tools.dataset_store import delete_dataset, get_dataset

    dataset = get_dataset(dataset_id)

    try:
        deleted = delete_dataset(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Dataset not found")
    from tools.workflow_store import record_audit_event

    record_audit_event(
        event_type="dataset_deleted",
        actor="demo.analyst",
        payload={
            "dataset_id": dataset_id,
            "display_name": dataset.display_name if dataset else None,
            "dataset_type": dataset.dataset_type if dataset else None,
        },
    )
    return {"status": "deleted", "dataset_id": dataset_id}


@app.get("/customers", tags=["evidence"])
def customers(
    search: str | None = ApiQuery(default=None, max_length=120),
    risk_label: str | None = ApiQuery(default=None),
    limit: int = ApiQuery(default=50, ge=1, le=100),
    offset: int = ApiQuery(default=0, ge=0),
) -> dict:
    """Return paginated customer activity ranked by current workflow risk."""
    from tools.customer_browser import list_customers

    allowed_risk = {"unscored", "low", "medium", "high"}
    if risk_label is not None and risk_label not in allowed_risk:
        raise HTTPException(status_code=422, detail="Unsupported risk label")
    items, total = list_customers(
        search=search,
        risk_label=risk_label,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [item.model_dump() for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get(
    "/customers/{account_id}",
    response_model=CustomerDetail,
    tags=["evidence"],
)
def customer_detail(account_id: str) -> CustomerDetail:
    """Return consolidated behavior, counterparties, and alerts for an account."""
    from tools.customer_browser import get_customer

    record = get_customer(account_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return record


@app.get("/transactions/payment-formats", tags=["evidence"])
def transaction_payment_formats() -> dict[str, list[str]]:
    from tools.transaction_browser import payment_formats

    return {"items": payment_formats()}


@app.get("/transactions", tags=["evidence"])
def transactions(
    account_id: str | None = ApiQuery(default=None, max_length=120),
    direction: str = ApiQuery(default="both"),
    payment_format: str | None = ApiQuery(default=None, max_length=120),
    min_amount: float | None = ApiQuery(default=None, ge=0),
    max_amount: float | None = ApiQuery(default=None, ge=0),
    date_from: date | None = ApiQuery(default=None),
    date_to: date | None = ApiQuery(default=None),
    laundering_only: bool = ApiQuery(default=False),
    limit: int = ApiQuery(default=50, ge=1, le=100),
    offset: int = ApiQuery(default=0, ge=0),
) -> dict:
    """Return a bounded evidence page with query-aware filters."""
    from tools.transaction_browser import list_transactions

    if direction not in {"both", "inbound", "outbound"}:
        raise HTTPException(status_code=422, detail="Unsupported direction")
    if direction != "both" and not account_id:
        raise HTTPException(
            status_code=422,
            detail="Direction requires an account_id filter",
        )
    if (
        min_amount is not None
        and max_amount is not None
        and min_amount > max_amount
    ):
        raise HTTPException(status_code=422, detail="min_amount exceeds max_amount")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from exceeds date_to")
    items, total = list_transactions(
        account_id=account_id,
        direction=direction,
        payment_format=payment_format,
        min_amount=min_amount,
        max_amount=max_amount,
        date_from=date_from,
        date_to=date_to,
        laundering_only=laundering_only,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [item.model_dump() for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/exports/investigations/{investigation_id}/entities", tags=["export"])
def export_investigation_entities(
    investigation_id: str,
    format: Literal["csv", "json", "xlsx"] = ApiQuery(default="csv"),
) -> StreamingResponse:
    return export_entities(format=format, investigation_id=investigation_id)


@app.get("/export/entities", tags=["export"])
def export_entities(
    format: Literal["csv", "json", "xlsx"] = ApiQuery(default="csv"),
    investigation_id: str | None = ApiQuery(default=None),
) -> StreamingResponse:
    """Export flagged entities from one immutable investigation record."""
    from tools.exporter import (
        export_entities_csv,
        export_entities_xlsx,
        export_json,
    )

    record = _load_investigation_or_latest(investigation_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    if format == "csv":
        return _download(
            export_entities_csv(record.response.top_entities),
            "text/csv; charset=utf-8",
            f"sentinel_entities_{stamp}.csv",
        )
    if format == "xlsx":
        return _download(
            export_entities_xlsx(record.response),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"sentinel_investigation_{stamp}.xlsx",
        )
    return _download(
        export_json([entity.model_dump(mode="json") for entity in record.response.top_entities]),
        "application/json",
        f"sentinel_entities_{stamp}.json",
    )


@app.get("/export/sar/{entity_id}", tags=["export"])
def export_sar(
    entity_id: str,
    format: Literal["txt", "pdf"] = ApiQuery(default="txt"),
    investigation_id: str | None = ApiQuery(default=None),
) -> StreamingResponse:
    """Export a human-review-only SAR draft for one flagged entity."""
    from tools.exporter import export_sar_pdf, export_sar_txt
    from tools.workflow_store import get_investigation, list_investigations

    records: list[InvestigationRecord] = []
    if investigation_id:
        record = get_investigation(investigation_id)
        if record:
            records.append(record)
    else:
        for summary in list_investigations(limit=100):
            record = get_investigation(summary.investigation_id)
            if record:
                records.append(record)
    entity = next(
        (
            candidate
            for record in records
            for candidate in record.response.top_entities
            if candidate.entity_id == entity_id
        ),
        None,
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Flagged entity not found")
    source_record = next(record for record in records
                         if any(candidate.entity_id == entity_id for candidate in record.response.top_entities))
    account_key = hashlib.sha256(entity_id.encode()).hexdigest()[:20]
    s3_key = f"sar-drafts/{source_record.investigation_id}/{account_key}/sar-draft.{format}"
    if format == "pdf":
        return _download(
            export_sar_pdf(entity),
            "application/pdf",
            f"sar_draft_{entity_id}.pdf",
            s3_key=s3_key,
        )
    return _download(
        export_sar_txt(entity),
        "text/plain; charset=utf-8",
        f"sar_draft_{entity_id}.txt",
        s3_key=s3_key,
    )


@app.get("/exports/investigations/{investigation_id}", tags=["export"])
@app.get("/export/investigation/{investigation_id}", tags=["export"])
def export_investigation(
    investigation_id: str,
    format: Literal["json", "md", "pdf"] = ApiQuery(default="pdf"),
) -> StreamingResponse:
    from tools.exporter import (
        export_investigation_md,
        export_investigation_pdf,
        export_json,
    )

    record = _load_investigation_or_latest(investigation_id)
    if format == "json":
        return _download(
            export_json(record),
            "application/json",
            f"investigation_{investigation_id}.json",
        )
    if format == "md":
        return _download(
            export_investigation_md(record.response, record.dataset_name),
            "text/markdown; charset=utf-8",
            f"investigation_{investigation_id}.md",
        )
    return _download(
        export_investigation_pdf(record.response),
        "application/pdf",
        f"investigation_{investigation_id}.pdf",
    )


@app.get("/exports/investigations/{investigation_id}/trace", tags=["export"])
@app.get("/export/trace/{investigation_id}", tags=["export"])
def export_trace(
    investigation_id: str,
    format: Literal["json", "csv"] = ApiQuery(default="csv"),
) -> StreamingResponse:
    from tools.exporter import export_json, export_trace_csv

    response = _load_investigation_or_latest(investigation_id).response
    if format == "json":
        content = export_json(
            [step.model_dump(mode="json") for step in response.execution_trace]
        )
        return _download(content, "application/json", f"trace_{investigation_id}.json")
    return _download(
        export_trace_csv(response),
        "text/csv; charset=utf-8",
        f"trace_{investigation_id}.csv",
    )


@app.get("/export/model-card", tags=["export"])
def export_active_model_card(
    format: Literal["json", "md", "pdf"] = ApiQuery(default="json"),
) -> StreamingResponse:
    from tools.exporter import export_json, export_model_card_md, export_model_card_pdf

    card = model_card()
    if format == "md":
        return _download(
            export_model_card_md(card),
            "text/markdown; charset=utf-8",
            "sentinel_model_card.md",
        )
    if format == "pdf":
        return _download(
            export_model_card_pdf(card),
            "application/pdf",
            "sentinel_model_card.pdf",
        )
    return _download(
        export_json(card),
        "application/json",
        "sentinel_model_card.json",
    )


@app.get("/export/audit", tags=["export"])
def export_audit(
    format: Literal["csv", "json"] = ApiQuery(default="csv"),
    from_date: date | None = ApiQuery(default=None),
    to_date: date | None = ApiQuery(default=None),
) -> StreamingResponse:
    from tools.exporter import export_audit_csv, export_json
    from tools.workflow_store import list_audit_events

    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from_date exceeds to_date")
    events, _ = list_audit_events(limit=50_000)
    filtered = [
        event
        for event in events
        if (not from_date or event.created_at[:10] >= str(from_date))
        and (not to_date or event.created_at[:10] <= str(to_date))
    ]
    if format == "json":
        return _download(
            export_json([event.model_dump(mode="json") for event in filtered]),
            "application/json",
            "sentinel_audit_trail.json",
        )
    return _download(
        export_audit_csv(filtered),
        "text/csv; charset=utf-8",
        "sentinel_audit_trail.csv",
    )


@app.get("/export/eda", tags=["export"])
def export_eda(
    format: Literal["json", "html", "pdf"] = ApiQuery(default="json"),
    investigation_id: str | None = ApiQuery(default=None),
) -> StreamingResponse:
    from tools.exporter import export_json, export_pdf

    record = _load_investigation_or_latest(investigation_id)
    payload = {
        "investigation_id": record.investigation_id,
        "dataset_id": record.dataset_id,
        "summary": record.response.eda_summary,
        "charts": record.response.charts,
    }
    if format == "html":
        encoded = json.dumps(payload, indent=2, default=str)
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Sentinel AML EDA report</title></head><body>"
            "<h1>Sentinel AML EDA Report</h1><p>Human review required.</p>"
            f"<pre>{html.escape(encoded)}</pre></body></html>"
        ).encode("utf-8")
        return _download(html, "text/html; charset=utf-8", "sentinel_eda.html")
    if format == "pdf":
        return _download(
            export_pdf(
                "Sentinel AML EDA Report",
                [("Summary and chart specifications", json.dumps(payload, indent=2, default=str))],
            ),
            "application/pdf",
            "sentinel_eda.pdf",
        )
    return _download(export_json(payload), "application/json", "sentinel_eda.json")


@app.post("/query", response_model=AgentResponse, tags=["agent"])
def query(request: QueryRequest) -> AgentResponse:
    """Run intent extraction, planning, and the current tool implementations."""
    runner = getattr(app.state, "agent_runner", None) or AgentRunner()
    try:
        from api.services.aws.logging import event
        event("investigation_started", dataset_id=request.dataset_id)
        response = runner.run(request.query, dataset_id=request.dataset_id)
        if getattr(app.state, "workflow_enabled", True):
            from tools.workflow_store import persist_investigation

            response = persist_investigation(response)
        return response
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Agent query failed")
        raise HTTPException(status_code=500, detail="Agent query failed") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
    )
