"""Persistent investigation, alert-queue, and immutable audit storage."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

import duckdb

from agent.models import (
    AgentResponse,
    AlertQueueItem,
    AuditEvent,
    InvestigationRecord,
    InvestigationSummary,
)
from tools.data_loader import get_db_connection


RISK_POLICY_VERSION = "sentinel-risk-policy-1.0.0"
MODEL_VERSION = "sentinel-saml-iforest-v1"
DATASET_SNAPSHOT = "HI-Small+SAML-D:active"

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS investigations (
        investigation_id       VARCHAR PRIMARY KEY,
        query                  TEXT NOT NULL,
        intent                 VARCHAR NOT NULL,
        pattern_type           VARCHAR,
        status                 VARCHAR NOT NULL DEFAULT 'open',
        disposition            VARCHAR DEFAULT 'pending',
        flagged_count          INTEGER NOT NULL DEFAULT 0,
        high_risk_count        INTEGER NOT NULL DEFAULT 0,
        response_json          JSON NOT NULL,
        created_at             TIMESTAMP NOT NULL,
        updated_at             TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alert_queue (
        alert_id               VARCHAR PRIMARY KEY,
        entity_id              VARCHAR NOT NULL,
        investigation_id       VARCHAR NOT NULL,
        risk_score             DOUBLE NOT NULL,
        risk_label             VARCHAR NOT NULL,
        escalation_action      VARCHAR NOT NULL,
        saml_d_typology        VARCHAR,
        created_at             TIMESTAMP NOT NULL,
        sla_hours              INTEGER NOT NULL,
        assigned_to            VARCHAR,
        status                 VARCHAR NOT NULL DEFAULT 'new',
        disposition            VARCHAR DEFAULT 'pending',
        notes                  TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        event_id               VARCHAR PRIMARY KEY,
        event_type             VARCHAR NOT NULL,
        actor                  VARCHAR NOT NULL,
        investigation_id       VARCHAR,
        alert_id               VARCHAR,
        payload                JSON NOT NULL,
        risk_policy_version    VARCHAR NOT NULL,
        model_version          VARCHAR NOT NULL,
        dataset_snapshot       VARCHAR NOT NULL,
        created_at             TIMESTAMP NOT NULL
    )
    """,
    # DuckDB 0.10 cannot reliably update a row when an indexed status column
    # changes alongside a primary key. Queue volumes are bounded in Phase B,
    # so correctness takes priority over a secondary status index.
    "DROP INDEX IF EXISTS alert_queue_status_idx",
    """
    CREATE INDEX IF NOT EXISTS audit_events_created_idx
    ON audit_events(created_at)
    """,
)
_SCHEMA_LOCK = Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: Any) -> str:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value)
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def _json(payload: Any) -> str:
    return json.dumps(payload, default=str, separators=(",", ":"))


def initialize_workflow_schema(
    conn: duckdb.DuckDBPyConnection | None = None,
) -> None:
    """Create Phase B workflow tables without modifying transaction tables."""
    own_conn = conn is None
    db = conn or get_db_connection()
    try:
        for statement in _SCHEMA_STATEMENTS:
            db.execute(statement)
    finally:
        if own_conn:
            db.close()


def ensure_workflow_schema(
    conn: duckdb.DuckDBPyConnection | None = None,
) -> None:
    """Initialize a fresh store without issuing DDL on normal request reads."""
    own_conn = conn is None
    db = conn or get_db_connection()

    def ready() -> bool:
        return int(
            db.execute(
                """
                SELECT count(*)
                FROM information_schema.tables
                WHERE table_schema = 'main'
                  AND table_name IN (
                      'investigations', 'alert_queue', 'audit_events'
                  )
                """
            ).fetchone()[0]
        ) == 3

    try:
        if ready():
            return
        with _SCHEMA_LOCK:
            if not ready():
                initialize_workflow_schema(db)
    finally:
        if own_conn:
            db.close()


def _insert_audit(
    db: duckdb.DuckDBPyConnection,
    *,
    event_type: str,
    actor: str,
    investigation_id: str | None,
    alert_id: str | None,
    payload: dict[str, Any],
    created_at: datetime | None = None,
) -> str:
    event_id = f"AUD-{uuid4().hex[:12].upper()}"
    db.execute(
        """
        INSERT INTO audit_events (
            event_id, event_type, actor, investigation_id, alert_id,
            payload, risk_policy_version, model_version, dataset_snapshot,
            created_at
        ) VALUES (?, ?, ?, ?, ?, CAST(? AS JSON), ?, ?, ?, ?)
        """,
        [
            event_id,
            event_type,
            actor,
            investigation_id,
            alert_id,
            _json(payload),
            RISK_POLICY_VERSION,
            MODEL_VERSION,
            DATASET_SNAPSHOT,
            created_at or _utc_now(),
        ],
    )
    return event_id


def record_audit_event(
    *,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
    investigation_id: str | None = None,
    alert_id: str | None = None,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> str:
    """Record a trusted system or governance action in the immutable audit log."""
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_workflow_schema(db)
    try:
        return _insert_audit(
            db,
            event_type=event_type,
            actor=actor,
            investigation_id=investigation_id,
            alert_id=alert_id,
            payload=payload,
        )
    finally:
        if own_conn:
            db.close()


def _persist_local_investigation(
    response: AgentResponse,
    actor: str = "sentinel.agent",
    conn: duckdb.DuckDBPyConnection | None = None,
) -> AgentResponse:
    """Atomically retain a response, queue its findings, and write audit events."""
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_workflow_schema(db)
    from api.services.aws.investigations import event_investigation_id
    investigation_id = event_investigation_id.get() or f"INV-{uuid4().hex[:12].upper()}"
    created_at = _utc_now()
    persisted = response.model_copy(
        update={"investigation_id": investigation_id}
    )

    try:
        db.execute("BEGIN TRANSACTION")
        db.execute(
            """
            INSERT INTO investigations (
                investigation_id, query, intent, pattern_type, status,
                disposition, flagged_count, high_risk_count, response_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'open', 'pending', ?, ?, CAST(? AS JSON), ?, ?)
            """,
            [
                investigation_id,
                persisted.query,
                persisted.intent.intent,
                persisted.intent.pattern_type,
                persisted.summary_stats.flagged,
                persisted.summary_stats.high_risk,
                persisted.model_dump_json(),
                created_at,
                created_at,
            ],
        )

        _insert_audit(
            db,
            event_type="query_received",
            actor=actor,
            investigation_id=investigation_id,
            alert_id=None,
            payload={
                "query": persisted.query,
                "intent": persisted.intent.model_dump(),
            },
            created_at=created_at,
        )
        _insert_audit(
            db,
            event_type="plan_created",
            actor=actor,
            investigation_id=investigation_id,
            alert_id=None,
            payload=persisted.plan.model_dump(),
            created_at=created_at,
        )
        for step in persisted.execution_trace:
            _insert_audit(
                db,
                event_type=(
                    "tool_executed"
                    if step.status == "run"
                    else "tool_skipped"
                ),
                actor=actor,
                investigation_id=investigation_id,
                alert_id=None,
                payload=step.model_dump(),
                created_at=created_at,
            )

        for entity in persisted.top_entities:
            alert_id = f"ALT-{uuid4().hex[:12].upper()}"
            sla_hours = {
                "report": 4,
                "flag_for_review": 24,
                "monitor": 72,
            }[entity.escalation_action]
            db.execute(
                """
                INSERT INTO alert_queue (
                    alert_id, entity_id, investigation_id, risk_score,
                    risk_label, escalation_action, saml_d_typology,
                    created_at, sla_hours, status, disposition, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', 'pending', '')
                """,
                [
                    alert_id,
                    entity.entity_id,
                    investigation_id,
                    entity.risk_score,
                    entity.risk_label,
                    entity.escalation_action,
                    entity.saml_d_typology,
                    created_at,
                    sla_hours,
                ],
            )
            _insert_audit(
                db,
                event_type="alert_created",
                actor=actor,
                investigation_id=investigation_id,
                alert_id=alert_id,
                payload={
                    "entity_id": entity.entity_id,
                    "risk_score": entity.risk_score,
                    "risk_label": entity.risk_label,
                    "recommended_action": entity.escalation_action,
                },
                created_at=created_at,
            )

        _insert_audit(
            db,
            event_type="investigation_completed",
            actor=actor,
            investigation_id=investigation_id,
            alert_id=None,
            payload=persisted.summary_stats.model_dump(),
            created_at=created_at,
        )
        db.execute("COMMIT")
        return persisted
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        if own_conn:
            db.close()


def _list_local_investigations(
    limit: int = 50,
    dataset_id: str | None = None,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> list[InvestigationSummary]:
    """Return newest investigation summaries without transferring full results."""
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_workflow_schema(db)
    try:
        rows = db.execute(
            """
            SELECT
                i.investigation_id,
                json_extract_string(i.response_json, '$.dataset_id'),
                json_extract_string(i.response_json, '$.dataset_name'),
                i.query, i.intent, i.pattern_type,
                i.status, i.disposition, i.flagged_count, i.high_risk_count,
                count(q.alert_id) AS alert_count, i.created_at, i.updated_at
            FROM investigations i
            LEFT JOIN alert_queue q
                ON q.investigation_id = i.investigation_id
            WHERE (? IS NULL OR
                   json_extract_string(i.response_json, '$.dataset_id') = ?)
            GROUP BY ALL
            ORDER BY i.created_at DESC
            LIMIT ?
            """,
            [dataset_id, dataset_id, limit],
        ).fetchall()
        return [
            InvestigationSummary(
                investigation_id=row[0],
                dataset_id=row[1],
                dataset_name=row[2],
                query=row[3],
                intent=row[4],
                pattern_type=row[5],
                status=row[6],
                disposition=row[7],
                flagged_count=row[8],
                high_risk_count=row[9],
                alert_count=row[10],
                created_at=_iso(row[11]),
                updated_at=_iso(row[12]),
            )
            for row in rows
        ]
    finally:
        if own_conn:
            db.close()


def _get_local_investigation(
    investigation_id: str,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> InvestigationRecord | None:
    """Load one complete persisted investigation."""
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_workflow_schema(db)
    try:
        row = db.execute(
            """
            SELECT i.investigation_id, i.query, i.intent, i.pattern_type,
                   i.status, i.disposition, i.flagged_count,
                   i.high_risk_count, i.response_json, i.created_at,
                   i.updated_at, count(q.alert_id) AS alert_count,
                   json_extract_string(i.response_json, '$.dataset_id'),
                   json_extract_string(i.response_json, '$.dataset_name')
            FROM investigations i
            LEFT JOIN alert_queue q
                ON q.investigation_id = i.investigation_id
            WHERE i.investigation_id = ?
            GROUP BY ALL
            """,
            [investigation_id],
        ).fetchone()
        if row is None:
            return None
        payload = row[8] if isinstance(row[8], dict) else json.loads(row[8])
        return InvestigationRecord(
            investigation_id=row[0],
            dataset_id=row[12],
            dataset_name=row[13],
            query=row[1],
            intent=row[2],
            pattern_type=row[3],
            status=row[4],
            disposition=row[5],
            flagged_count=row[6],
            high_risk_count=row[7],
            alert_count=row[11],
            response=AgentResponse.model_validate(payload),
            created_at=_iso(row[9]),
            updated_at=_iso(row[10]),
        )
    finally:
        if own_conn:
            db.close()


def _queue_item(row: tuple[Any, ...], now: datetime | None = None) -> AlertQueueItem:
    created_at = row[7]
    reference = now or _utc_now()
    age_hours = max(
        0.0,
        (reference - created_at).total_seconds() / 3_600,
    )
    return AlertQueueItem(
        alert_id=row[0],
        entity_id=row[1],
        investigation_id=row[2],
        risk_score=float(row[3]),
        risk_label=row[4],
        escalation_action=row[5],
        saml_d_typology=row[6] or "",
        created_at=_iso(created_at),
        sla_hours=int(row[8]),
        age_hours=round(age_hours, 2),
        assigned_to=row[9],
        status=row[10],
        disposition=row[11],
        notes=row[12] or "",
    )


_QUEUE_SELECT = """
SELECT alert_id, entity_id, investigation_id, risk_score, risk_label,
       escalation_action, saml_d_typology, created_at, sla_hours,
       assigned_to, status, disposition, notes
FROM alert_queue
"""


def list_queue(
    status: str | None = None,
    limit: int = 100,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> list[AlertQueueItem]:
    """Return risk-ranked queue items, optionally filtered by workflow status."""
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_workflow_schema(db)
    try:
        if status:
            rows = db.execute(
                _QUEUE_SELECT
                + " WHERE status = ? ORDER BY risk_score DESC, created_at ASC LIMIT ?",
                [status, limit],
            ).fetchall()
        else:
            rows = db.execute(
                _QUEUE_SELECT
                + " ORDER BY CASE status WHEN 'escalated' THEN 0 "
                "WHEN 'new' THEN 1 WHEN 'in_review' THEN 2 ELSE 3 END, "
                "risk_score DESC, created_at ASC LIMIT ?",
                [limit],
            ).fetchall()
        now = _utc_now()
        return [_queue_item(row, now) for row in rows]
    finally:
        if own_conn:
            db.close()


def get_queue_item(
    alert_id: str,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> AlertQueueItem | None:
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_workflow_schema(db)
    try:
        row = db.execute(
            _QUEUE_SELECT + " WHERE alert_id = ?",
            [alert_id],
        ).fetchone()
        return _queue_item(row) if row else None
    finally:
        if own_conn:
            db.close()


def list_entity_alerts(
    entity_id: str,
    limit: int = 25,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> list[AlertQueueItem]:
    """Return newest workflow alerts for one exact entity identifier."""
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_workflow_schema(db)
    try:
        rows = db.execute(
            _QUEUE_SELECT
            + " WHERE entity_id = ? ORDER BY created_at DESC LIMIT ?",
            [entity_id, limit],
        ).fetchall()
        now = _utc_now()
        return [_queue_item(row, now) for row in rows]
    finally:
        if own_conn:
            db.close()


def _refresh_investigation_status(
    db: duckdb.DuckDBPyConnection,
    investigation_id: str,
) -> None:
    queue_rows = [
        row
        for row in db.execute(
            """
            SELECT status, disposition
            FROM alert_queue
            WHERE investigation_id = ?
            """,
            [investigation_id],
        ).fetchall()
    ]
    statuses = [row[0] for row in queue_rows]
    if "escalated" in statuses:
        status = "escalated"
    elif any(item in {"new", "in_review"} for item in statuses):
        status = "in_review"
    else:
        status = "closed"
    dispositions = [row[1] for row in queue_rows if row[1] != "pending"]
    if status == "escalated":
        disposition = "escalated"
    elif status == "closed" and "true_positive" in dispositions:
        disposition = "true_positive"
    elif status == "closed" and dispositions:
        disposition = "false_positive"
    else:
        disposition = "pending"
    db.execute(
        """
        UPDATE investigations
        SET status = ?, disposition = ?, updated_at = ?
        WHERE investigation_id = ?
        """,
        [status, disposition, _utc_now(), investigation_id],
    )


def _assign_local_alert(
    alert_id: str,
    assigned_to: str,
    actor: str,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> AlertQueueItem | None:
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_workflow_schema(db)
    try:
        existing = get_queue_item(alert_id, db)
        if existing is None:
            return None
        db.execute("BEGIN TRANSACTION")
        db.execute(
            """
            UPDATE alert_queue
            SET assigned_to = ?, status = 'in_review'
            WHERE alert_id = ?
            """,
            [assigned_to.strip(), alert_id],
        )
        _refresh_investigation_status(db, existing.investigation_id)
        _insert_audit(
            db,
            event_type="alert_assigned",
            actor=actor,
            investigation_id=existing.investigation_id,
            alert_id=alert_id,
            payload={"assigned_to": assigned_to.strip()},
        )
        db.execute("COMMIT")
        return get_queue_item(alert_id, db)
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        if own_conn:
            db.close()


def _disposition_local_alert(
    alert_id: str,
    disposition: str,
    actor: str,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> AlertQueueItem | None:
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_workflow_schema(db)
    try:
        existing = get_queue_item(alert_id, db)
        if existing is None:
            return None
        status = (
            "escalated"
            if disposition in {"escalated", "sar_filed"}
            else "closed"
        )
        db.execute("BEGIN TRANSACTION")
        db.execute(
            """
            UPDATE alert_queue
            SET disposition = ?, status = ?
            WHERE alert_id = ?
            """,
            [disposition, status, alert_id],
        )
        _refresh_investigation_status(db, existing.investigation_id)
        _insert_audit(
            db,
            event_type="alert_dispositioned",
            actor=actor,
            investigation_id=existing.investigation_id,
            alert_id=alert_id,
            payload={"disposition": disposition, "status": status},
        )
        db.execute("COMMIT")
        return get_queue_item(alert_id, db)
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        if own_conn:
            db.close()


def append_alert_note(
    alert_id: str,
    note: str,
    actor: str,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> AlertQueueItem | None:
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_workflow_schema(db)
    try:
        existing = get_queue_item(alert_id, db)
        if existing is None:
            return None
        timestamp = _iso(_utc_now())
        entry = f"[{timestamp}] {actor}: {note.strip()}"
        notes = f"{existing.notes}\n{entry}".strip()
        db.execute("BEGIN TRANSACTION")
        db.execute(
            "UPDATE alert_queue SET notes = ? WHERE alert_id = ?",
            [notes, alert_id],
        )
        _insert_audit(
            db,
            event_type="analyst_note_added",
            actor=actor,
            investigation_id=existing.investigation_id,
            alert_id=alert_id,
            payload={"note": note.strip()},
        )
        db.execute("COMMIT")
        return get_queue_item(alert_id, db)
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        if own_conn:
            db.close()


def list_audit_events(
    limit: int = 100,
    offset: int = 0,
    event_type: str | None = None,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> tuple[list[AuditEvent], int]:
    """Return immutable audit records and the filtered total."""
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_workflow_schema(db)
    try:
        where = "WHERE event_type = ?" if event_type else ""
        params: list[Any] = [event_type] if event_type else []
        total = int(
            db.execute(
                f"SELECT count(*) FROM audit_events {where}",
                params,
            ).fetchone()[0]
        )
        rows = db.execute(
            f"""
            SELECT event_id, event_type, actor, investigation_id, alert_id,
                   payload, risk_policy_version, model_version,
                   dataset_snapshot, created_at
            FROM audit_events
            {where}
            ORDER BY created_at DESC, event_id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        events = []
        for row in rows:
            payload = row[5] if isinstance(row[5], dict) else json.loads(row[5])
            events.append(
                AuditEvent(
                    event_id=row[0],
                    event_type=row[1],
                    actor=row[2],
                    investigation_id=row[3],
                    alert_id=row[4],
                    dataset_id=payload.get("dataset_id"),
                    payload=payload,
                    risk_policy_version=row[6],
                    model_version=row[7],
                    dataset_snapshot=row[8],
                    created_at=_iso(row[9]),
                )
            )
        return events, total
    finally:
        if own_conn:
            db.close()


def queue_summary(
    conn: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, int]:
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_workflow_schema(db)
    try:
        rows = db.execute(
            "SELECT status, count(*) FROM alert_queue GROUP BY status"
        ).fetchall()
        counts = {row[0]: int(row[1]) for row in rows}
        return {
            "total": sum(counts.values()),
            "new": counts.get("new", 0),
            "in_review": counts.get("in_review", 0),
            "escalated": counts.get("escalated", 0),
            "closed": counts.get("closed", 0),
        }
    finally:
        if own_conn:
            db.close()


def persist_investigation(
    response: AgentResponse,
    actor: str = "sentinel.agent",
    conn: duckdb.DuckDBPyConnection | None = None,
) -> AgentResponse:
    """Preserve local workflow; AWS metadata/evidence use durable adapters."""
    from api.services.aws.settings import enabled
    from api.services.aws.investigations import event_investigation_id
    event_id = event_investigation_id.get() if enabled() else None
    existing = _get_local_investigation(event_id, conn) if event_id else None
    persisted = existing.response if existing else _persist_local_investigation(response, actor, conn)
    if enabled():
        if conn is None:
            from api.services.aws.runtime import checkpoint
            # Persist the queue/audit commit before publishing external results.
            checkpoint()
        from api.services.aws.investigations import save
        save(_get_local_investigation(persisted.investigation_id, conn))
        from api.services.aws.completion import complete
        from api.services.aws.logging import event
        try:
            if not event_id:
                complete(persisted)
        except Exception as exc:
            # Durable response remains available when report generation fails.
            event("investigation_artifact_failed", investigation_id=persisted.investigation_id,
                  error_type=type(exc).__name__)
    return persisted


def list_investigations(
    limit: int = 50,
    dataset_id: str | None = None,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> list[InvestigationSummary]:
    from api.services.aws.settings import enabled
    if enabled() and conn is None:
        from api.services.aws.investigations import list_records
        return list_records(limit, dataset_id)
    return _list_local_investigations(limit, dataset_id, conn)


def get_investigation(
    investigation_id: str,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> InvestigationRecord | None:
    from api.services.aws.settings import enabled
    if enabled() and conn is None:
        from api.services.aws.investigations import get
        return get(investigation_id)
    return _get_local_investigation(investigation_id, conn)


def _sync_aws_workflow(item: AlertQueueItem | None, conn=None) -> AlertQueueItem | None:
    from api.services.aws.settings import enabled
    if enabled() and item:
        if conn is None:
            from api.services.aws.runtime import checkpoint
            checkpoint()
        from api.services.aws.investigations import sync_workflow
        from api.services.aws.dynamodb_service import InvestigationRepository
        sync_workflow(_get_local_investigation(item.investigation_id, conn))
        InvestigationRepository().update_investigation(item.investigation_id,
                                                       {"assigned_to": item.assigned_to})
    return item


def assign_alert(alert_id: str, assigned_to: str, actor: str, conn=None) -> AlertQueueItem | None:
    return _sync_aws_workflow(_assign_local_alert(alert_id, assigned_to, actor, conn), conn)


def disposition_alert(alert_id: str, disposition: str, actor: str, conn=None) -> AlertQueueItem | None:
    return _sync_aws_workflow(_disposition_local_alert(alert_id, disposition, actor, conn), conn)
