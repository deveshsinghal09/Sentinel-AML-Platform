"""Transactional DuckDB repository for analyst review workflow state."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import uuid4

import duckdb

from tools.data_loader import get_db_connection


_SCHEMA_LOCK = Lock()
_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS governed_alert_queue (
        alert_id VARCHAR PRIMARY KEY,
        entity_id VARCHAR NOT NULL,
        investigation_id VARCHAR NOT NULL,
        risk_score DOUBLE NOT NULL,
        risk_label VARCHAR NOT NULL,
        escalation_action VARCHAR NOT NULL,
        typology VARCHAR NOT NULL DEFAULT '',
        created_at TIMESTAMP NOT NULL,
        sla_hours INTEGER NOT NULL,
        assigned_to VARCHAR,
        status VARCHAR NOT NULL DEFAULT 'new',
        disposition VARCHAR NOT NULL DEFAULT 'pending',
        notes TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS governed_audit_events (
        event_id VARCHAR PRIMARY KEY,
        event_type VARCHAR NOT NULL,
        actor VARCHAR NOT NULL,
        alert_id VARCHAR,
        investigation_id VARCHAR,
        payload JSON NOT NULL,
        created_at TIMESTAMP NOT NULL
    )
    """,
)


class WorkflowRepository:
    """Store queue changes and immutable audit evidence in one transaction."""

    def __init__(self, connection_factory=get_db_connection):
        self._connection_factory = connection_factory

    def _connection(self) -> duckdb.DuckDBPyConnection:
        connection = self._connection_factory()
        with _SCHEMA_LOCK:
            for statement in _SCHEMA:
                connection.execute(statement)
        return connection

    def list_alerts(
        self,
        *,
        status: str | None,
        assigned_to: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        where: list[str] = []
        parameters: list[Any] = []
        if status:
            where.append("status = ?")
            parameters.append(status)
        if assigned_to:
            where.append("assigned_to = ?")
            parameters.append(assigned_to)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        db = self._connection()
        try:
            total = int(
                db.execute(
                    f"SELECT count(*) FROM governed_alert_queue {clause}",
                    parameters,
                ).fetchone()[0]
            )
            rows = db.execute(
                f"""
                SELECT alert_id, entity_id, investigation_id, risk_score,
                       risk_label, escalation_action, typology, created_at,
                       sla_hours, assigned_to, status, disposition, notes,
                       greatest(
                           0,
                           date_diff('second', created_at, current_timestamp)
                           / 3600.0
                       ) AS age_hours
                FROM governed_alert_queue
                {clause}
                ORDER BY
                    CASE risk_label
                        WHEN 'high' THEN 0
                        WHEN 'medium' THEN 1
                        ELSE 2
                    END,
                    created_at
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
            return [self._alert_row(row) for row in rows], total
        finally:
            db.close()

    def queue_summary(self) -> dict[str, int]:
        db = self._connection()
        try:
            rows = db.execute(
                """
                SELECT status, count(*)
                FROM governed_alert_queue
                GROUP BY status
                """
            ).fetchall()
            counts = {str(status): int(count) for status, count in rows}
            return {
                "total": sum(counts.values()),
                "new": counts.get("new", 0),
                "in_review": counts.get("in_review", 0),
                "escalated": counts.get("escalated", 0),
                "closed": counts.get("closed", 0),
            }
        finally:
            db.close()

    def assign(self, alert_id: str, analyst: str, actor: str) -> dict[str, Any]:
        return self._mutate(
            alert_id,
            actor=actor,
            event_type="alert_assigned",
            update_sql=(
                "assigned_to = ?, "
                "status = CASE WHEN status = 'new' THEN 'in_review' ELSE status END"
            ),
            values=[analyst],
            payload={"assigned_to": analyst},
        )

    def disposition(
        self,
        alert_id: str,
        disposition: str,
        actor: str,
    ) -> dict[str, Any]:
        next_status = {
            "true_positive": "in_review",
            "false_positive": "closed",
            "escalated": "escalated",
        }[disposition]
        return self._mutate(
            alert_id,
            actor=actor,
            event_type="alert_dispositioned",
            update_sql="disposition = ?, status = ?",
            values=[disposition, next_status],
            payload={"disposition": disposition, "status": next_status},
        )

    def append_note(self, alert_id: str, note: str, actor: str) -> dict[str, Any]:
        stamped = f"[{datetime.now(UTC).isoformat()}] {actor}: {note}"
        return self._mutate(
            alert_id,
            actor=actor,
            event_type="alert_note_added",
            update_sql=(
                "notes = CASE WHEN notes = '' THEN ? ELSE notes || chr(10) || ? END"
            ),
            values=[stamped, stamped],
            payload={"note_length": len(note)},
        )

    def list_audit(
        self,
        *,
        alert_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        clause = "WHERE alert_id = ?" if alert_id else ""
        parameters: list[Any] = [alert_id] if alert_id else []
        db = self._connection()
        try:
            total = int(
                db.execute(
                    f"SELECT count(*) FROM governed_audit_events {clause}",
                    parameters,
                ).fetchone()[0]
            )
            rows = db.execute(
                f"""
                SELECT event_id, event_type, actor, alert_id,
                       investigation_id, payload, created_at
                FROM governed_audit_events
                {clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
            return [
                {
                    "event_id": row[0],
                    "event_type": row[1],
                    "actor": row[2],
                    "alert_id": row[3],
                    "investigation_id": row[4],
                    "payload": json.loads(row[5]) if isinstance(row[5], str) else row[5],
                    "created_at": self._iso(row[6]),
                }
                for row in rows
            ], total
        finally:
            db.close()

    def _mutate(
        self,
        alert_id: str,
        *,
        actor: str,
        event_type: str,
        update_sql: str,
        values: list[Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        db = self._connection()
        try:
            db.execute("BEGIN TRANSACTION")
            existing = db.execute(
                """
                SELECT investigation_id
                FROM governed_alert_queue
                WHERE alert_id = ?
                """,
                [alert_id],
            ).fetchone()
            if existing is None:
                db.execute("ROLLBACK")
                raise KeyError(alert_id)
            db.execute(
                f"UPDATE governed_alert_queue SET {update_sql} WHERE alert_id = ?",
                [*values, alert_id],
            )
            db.execute(
                """
                INSERT INTO governed_audit_events
                VALUES (?, ?, ?, ?, ?, CAST(? AS JSON), ?)
                """,
                [
                    f"AUD-{uuid4().hex[:12].upper()}",
                    event_type,
                    actor,
                    alert_id,
                    existing[0],
                    json.dumps(payload, separators=(",", ":")),
                    datetime.now(UTC).replace(tzinfo=None),
                ],
            )
            row = db.execute(
                """
                SELECT alert_id, entity_id, investigation_id, risk_score,
                       risk_label, escalation_action, typology, created_at,
                       sla_hours, assigned_to, status, disposition, notes,
                       greatest(
                           0,
                           date_diff('second', created_at, current_timestamp)
                           / 3600.0
                       )
                FROM governed_alert_queue
                WHERE alert_id = ?
                """,
                [alert_id],
            ).fetchone()
            db.execute("COMMIT")
            return self._alert_row(row)
        except Exception:
            try:
                db.execute("ROLLBACK")
            except duckdb.TransactionException:
                pass
            raise
        finally:
            db.close()

    @classmethod
    def _alert_row(cls, row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "alert_id": row[0],
            "entity_id": row[1],
            "investigation_id": row[2],
            "risk_score": float(row[3]),
            "risk_label": row[4],
            "escalation_action": row[5],
            "typology": row[6],
            "created_at": cls._iso(row[7]),
            "sla_hours": int(row[8]),
            "assigned_to": row[9],
            "status": row[10],
            "disposition": row[11],
            "notes": row[12],
            "age_hours": round(float(row[13]), 3),
        }

    @staticmethod
    def _iso(value: Any) -> str:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
