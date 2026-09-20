"""Governed registry and isolated DuckDB workspaces for uploaded datasets."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any

import duckdb
import pandas as pd

from tools.data_loader import (
    _SAML_SOURCE_COLUMNS,
    _insert_frame,
    _normalise_saml_rows,
    _saml_ddl,
    _table_exists,
    _transaction_ddl,
    get_db_connection,
    get_saml_summary_stats,
    get_summary_stats,
)

if TYPE_CHECKING:
    from agent.models import DatasetInfo, DatasetSwitchResult, DatasetUploadResult


_REGISTRY_LOCK = RLock()
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_FINGERPRINT = re.compile(r"^[a-f0-9]{32,64}$")
_DATASET_TYPES = {"primary", "knowledge", "kyc"}

_REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS dataset_registry (
    dataset_id          VARCHAR PRIMARY KEY,
    display_name        VARCHAR NOT NULL,
    source_file         VARCHAR,
    dataset_type        VARCHAR NOT NULL,
    file_size_bytes     BIGINT DEFAULT 0,
    row_count           BIGINT DEFAULT 0,
    laundering_count    BIGINT DEFAULT 0,
    laundering_rate     DOUBLE DEFAULT 0,
    date_min            DATE,
    date_max            DATE,
    schema_version      VARCHAR DEFAULT '1.0',
    md5_fingerprint     VARCHAR,
    ingested_at         TIMESTAMP DEFAULT now(),
    is_active           BOOLEAN DEFAULT false,
    notes               TEXT DEFAULT '',
    column_map          JSON,
    schema_detected     VARCHAR DEFAULT '',
    workspace_schema    VARCHAR NOT NULL,
    table_name          VARCHAR NOT NULL,
    protected           BOOLEAN DEFAULT false
)
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: Any) -> str:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def _ready(db: duckdb.DuckDBPyConnection) -> bool:
    return bool(
        db.execute(
            """
            SELECT count(*) FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = 'dataset_registry'
            """
        ).fetchone()[0]
    )


def initialize_dataset_registry(
    conn: duckdb.DuckDBPyConnection | None = None,
) -> None:
    own_conn = conn is None
    db = conn or get_db_connection()
    try:
        db.execute(_REGISTRY_DDL)
        if _table_exists(db, "transactions"):
            stats = get_summary_stats(conn=db)
            db.execute(
                """
                INSERT INTO dataset_registry (
                    dataset_id, display_name, source_file, dataset_type,
                    row_count, laundering_count, laundering_rate, date_min,
                    date_max, md5_fingerprint, is_active, notes, column_map,
                    schema_detected, workspace_schema, table_name, protected
                )
                SELECT ?, ?, ?, 'primary', ?, ?, ?, ?, ?, ?, true, ?,
                       CAST(? AS JSON), 'ibm_aml', 'main', 'transactions', true
                WHERE NOT EXISTS (
                    SELECT 1 FROM dataset_registry WHERE dataset_id = ?
                )
                """,
                [
                    "ibm-hi-small-v1",
                    "HI-Small Transactions",
                    "HI-Small_Trans.csv",
                    stats["total_rows"],
                    stats["laundering_count"],
                    stats["laundering_rate_pct"] / 100,
                    stats["date_min"],
                    stats["date_max"],
                    "managed:ibm-hi-small-v1",
                    "Built-in IBM AML investigation dataset",
                    json.dumps({}),
                    "ibm-hi-small-v1",
                ],
            )
        if _table_exists(db, "saml_knowledge"):
            stats = get_saml_summary_stats(conn=db)
            db.execute(
                """
                INSERT INTO dataset_registry (
                    dataset_id, display_name, source_file, dataset_type,
                    row_count, laundering_count, laundering_rate,
                    md5_fingerprint, is_active, notes, column_map,
                    schema_detected, workspace_schema, table_name, protected
                )
                SELECT ?, ?, ?, 'knowledge', ?, ?, ?, ?, true, ?,
                       CAST(? AS JSON), 'saml_d', 'main', 'saml_knowledge', true
                WHERE NOT EXISTS (
                    SELECT 1 FROM dataset_registry WHERE dataset_id = ?
                )
                """,
                [
                    "saml-d-knowledge-v1",
                    "SAML-D Knowledge",
                    "SAML-D.csv",
                    stats["total_rows"],
                    stats["laundering_count"],
                    (
                        stats["laundering_count"] / stats["total_rows"]
                        if stats["total_rows"] else 0
                    ),
                    "managed:saml-d-knowledge-v1",
                    "Typology grounding and ML calibration dataset",
                    json.dumps({}),
                    "saml-d-knowledge-v1",
                ],
            )
    finally:
        if own_conn:
            db.close()


def ensure_dataset_registry(
    conn: duckdb.DuckDBPyConnection | None = None,
) -> None:
    own_conn = conn is None
    db = conn or get_db_connection()
    try:
        if _ready(db):
            return
        with _REGISTRY_LOCK:
            if not _ready(db):
                initialize_dataset_registry(db)
    finally:
        if own_conn:
            db.close()


def _dataset(row: tuple[Any, ...]) -> DatasetInfo:
    from agent.models import DatasetInfo

    raw_map = row[14]
    column_map = raw_map if isinstance(raw_map, dict) else json.loads(raw_map or "{}")
    return DatasetInfo(
        dataset_id=row[0],
        display_name=row[1],
        source_file=row[2],
        dataset_type=row[3],
        file_size_bytes=int(row[4] or 0),
        row_count=int(row[5] or 0),
        laundering_count=int(row[6] or 0),
        laundering_rate=float(row[7] or 0),
        date_min=str(row[8]) if row[8] is not None else None,
        date_max=str(row[9]) if row[9] is not None else None,
        schema_version=row[10] or "1.0",
        md5_fingerprint=row[11],
        ingested_at=_iso(row[12]),
        is_active=bool(row[13]),
        notes=row[15] or "",
        column_map=column_map,
        schema_detected=row[16] or "",
    )


_SELECT_REGISTRY = """
SELECT dataset_id, display_name, source_file, dataset_type, file_size_bytes,
       row_count, laundering_count, laundering_rate, date_min, date_max,
       schema_version, md5_fingerprint, ingested_at, is_active, column_map,
       notes, schema_detected, workspace_schema, table_name, protected
FROM dataset_registry
"""


def list_datasets(
    conn: duckdb.DuckDBPyConnection | None = None,
) -> list[DatasetInfo]:
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_dataset_registry(db)
    try:
        rows = db.execute(
            _SELECT_REGISTRY
            + " ORDER BY is_active DESC, dataset_type, ingested_at DESC"
        ).fetchall()
        return [_dataset(row) for row in rows]
    finally:
        if own_conn:
            db.close()


def get_dataset(
    dataset_id: str,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> DatasetInfo | None:
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_dataset_registry(db)
    try:
        row = db.execute(
            _SELECT_REGISTRY + " WHERE dataset_id = ?",
            [dataset_id],
        ).fetchone()
        return _dataset(row) if row else None
    finally:
        if own_conn:
            db.close()


def active_dataset(
    dataset_type: str = "primary",
    conn: duckdb.DuckDBPyConnection | None = None,
) -> DatasetInfo | None:
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_dataset_registry(db)
    try:
        row = db.execute(
            _SELECT_REGISTRY
            + " WHERE dataset_type = ? AND is_active = true"
            + " ORDER BY ingested_at DESC LIMIT 1",
            [dataset_type],
        ).fetchone()
        return _dataset(row) if row else None
    finally:
        if own_conn:
            db.close()


def _table_metadata(
    db: duckdb.DuckDBPyConnection,
    dataset_id: str | None,
) -> tuple[str, str, str, int]:
    ensure_dataset_registry(db)
    if dataset_id:
        row = db.execute(
            """
            SELECT dataset_id, display_name, workspace_schema, table_name,
                   row_count, dataset_type
            FROM dataset_registry WHERE dataset_id = ?
            """,
            [dataset_id],
        ).fetchone()
    else:
        row = db.execute(
            """
            SELECT dataset_id, display_name, workspace_schema, table_name,
                   row_count, dataset_type
            FROM dataset_registry
            WHERE dataset_type = 'primary' AND is_active = true
            ORDER BY ingested_at DESC LIMIT 1
            """
        ).fetchone()
    if row is None:
        raise ValueError("Dataset not found")
    if row[5] != "primary":
        raise ValueError("Only primary transaction datasets can be analyzed")
    schema, table = row[2], row[3]
    if not _IDENTIFIER.fullmatch(schema) or not _IDENTIFIER.fullmatch(table):
        raise ValueError("Unsafe dataset workspace identifier")
    return f'"{schema}"."{table}"', row[0], row[1], int(row[4])


def resolve_transaction_table(
    conn: duckdb.DuckDBPyConnection,
    dataset_id: str | None = None,
) -> str:
    return _table_metadata(conn, dataset_id)[0]


def resolve_dataset_context(
    conn: duckdb.DuckDBPyConnection,
    dataset_id: str | None = None,
) -> tuple[str, str, int]:
    _, resolved_id, name, rows = _table_metadata(db=conn, dataset_id=dataset_id)
    return resolved_id, name, rows


def resolve_knowledge_table(
    conn: duckdb.DuckDBPyConnection,
) -> tuple[str, str]:
    ensure_dataset_registry(conn)
    row = conn.execute(
        """
        SELECT dataset_id, workspace_schema, table_name
        FROM dataset_registry
        WHERE dataset_type = 'knowledge' AND is_active = true
        ORDER BY ingested_at DESC LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise ValueError("Active knowledge dataset not found")
    if not _IDENTIFIER.fullmatch(row[1]) or not _IDENTIFIER.fullmatch(row[2]):
        raise ValueError("Unsafe knowledge workspace identifier")
    return f'"{row[1]}"."{row[2]}"', row[0]


def register_uploaded_dataset(
    *,
    path: Path,
    display_name: str,
    dataset_type: str,
    md5_fingerprint: str,
    file_size_bytes: int,
    source_file: str | None = None,
    force: bool = False,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> DatasetUploadResult:
    """Validate and register one dataset under the process write lock."""
    with _REGISTRY_LOCK:
        return _register_uploaded_dataset(
            path=path,
            display_name=display_name,
            dataset_type=dataset_type,
            md5_fingerprint=md5_fingerprint,
            file_size_bytes=file_size_bytes,
            source_file=source_file,
            force=force,
            conn=conn,
        )


def _register_uploaded_dataset(
    *,
    path: Path,
    display_name: str,
    dataset_type: str,
    md5_fingerprint: str,
    file_size_bytes: int,
    source_file: str | None = None,
    force: bool = False,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> DatasetUploadResult:
    from agent.models import DatasetUploadResult
    from tools.importer import (
        MIN_ANALYTICAL_ROWS,
        inspect_upload,
        iter_primary_frames,
    )

    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Dataset upload not found at {path}")
    display_name = display_name.strip()
    if not 3 <= len(display_name) <= 120:
        raise ValueError("display_name must contain between 3 and 120 characters")
    if dataset_type not in _DATASET_TYPES:
        raise ValueError("dataset_type must be primary, knowledge, or kyc")
    md5_fingerprint = md5_fingerprint.strip().lower()
    if not _FINGERPRINT.fullmatch(md5_fingerprint):
        raise ValueError("md5_fingerprint must be a lowercase hexadecimal digest")
    actual_size = path.stat().st_size
    if file_size_bytes != actual_size:
        raise ValueError("file_size_bytes does not match the uploaded file")
    source_file = Path(source_file).name if source_file else path.name

    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_dataset_registry(db)
    inspection = inspect_upload(path)
    dataset_id = f"ds_{md5_fingerprint[:12]}"
    if not _IDENTIFIER.fullmatch(dataset_id):
        raise ValueError("Unable to derive a safe dataset identifier")
    try:
        duplicate = db.execute(
            "SELECT dataset_id FROM dataset_registry WHERE md5_fingerprint = ?",
            [md5_fingerprint],
        ).fetchone()
        if duplicate and not force:
            raise ValueError(f"Dataset already registered as {duplicate[0]}")
        if duplicate and force:
            delete_dataset(duplicate[0], db, remove_source_file=False)

        schema = dataset_id
        db.execute(f'CREATE SCHEMA "{schema}"')
        warnings = list(inspection.warnings)
        row_count = 0
        laundering_count = 0
        date_min = None
        date_max = None
        table_name = "transactions"
        registry_transaction = False
        try:
            if dataset_type == "primary":
                if inspection.schema_name in {"unmapped", "saml_d"}:
                    raise ValueError(
                        "Primary datasets require a mapped transaction schema"
                    )
                qualified = f'"{schema}"."transactions"'
                db.execute(_transaction_ddl(qualified))
                for index, frame in enumerate(
                    iter_primary_frames(path, inspection.column_map),
                    start=1,
                ):
                    _insert_frame(db, qualified, frame, f"_upload_chunk_{index}")
                    row_count += len(frame)
                    laundering_count += int(frame["is_laundering"].sum())
                if row_count < MIN_ANALYTICAL_ROWS:
                    raise ValueError(
                        f"At least {MIN_ANALYTICAL_ROWS} valid rows are required"
                    )
                date_min, date_max = db.execute(
                    f"SELECT min(txn_date), max(txn_date) FROM {qualified}"
                ).fetchone()
            elif dataset_type == "knowledge":
                if inspection.schema_name != "saml_d":
                    raise ValueError("Knowledge uploads currently require SAML-D columns")
                table_name = "saml_knowledge"
                qualified = f'"{schema}"."saml_knowledge"'
                db.execute(_saml_ddl(qualified))
                reader = (
                    pd.read_csv(
                        path, dtype=str, keep_default_na=False,
                        low_memory=False, chunksize=100_000,
                    )
                    if path.suffix.lower() == ".csv"
                    else [pd.read_excel(path, dtype=str, keep_default_na=False)]
                )
                for index, raw in enumerate(reader, start=1):
                    missing = sorted(_SAML_SOURCE_COLUMNS.difference(raw.columns))
                    if missing:
                        raise ValueError("Missing SAML-D columns: " + ", ".join(missing))
                    frame = _normalise_saml_rows(raw)
                    _insert_frame(db, qualified, frame, f"_knowledge_chunk_{index}")
                    row_count += len(frame)
                    laundering_count += int(frame["is_laundering"].sum())
                date_min, date_max = db.execute(
                    f"SELECT min(txn_date), max(txn_date) FROM {qualified}"
                ).fetchone()
            else:
                table_name = "records"
                raw = (
                    pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
                    if path.suffix.lower() == ".csv"
                    else pd.read_excel(path, dtype=str, keep_default_na=False)
                )
                if len(raw) < 1:
                    raise ValueError("KYC upload contains no rows")
                db.register("_kyc_upload", raw)
                try:
                    db.execute(
                        f'CREATE TABLE "{schema}"."records" AS SELECT * FROM _kyc_upload'
                    )
                finally:
                    db.unregister("_kyc_upload")
                row_count = len(raw)

            rate = laundering_count / row_count if row_count else 0.0
            result = DatasetUploadResult(
                dataset_id=dataset_id,
                display_name=display_name,
                row_count=row_count,
                schema_detected=inspection.schema_name,
                warnings=warnings,
                eda_summary={
                    "rows": row_count,
                    "laundering_count": laundering_count,
                    "laundering_rate": rate,
                    "date_min": str(date_min) if date_min else None,
                    "date_max": str(date_max) if date_max else None,
                },
            )
            db.execute("BEGIN TRANSACTION")
            registry_transaction = True
            if dataset_type in {"primary", "knowledge"}:
                db.execute(
                    "UPDATE dataset_registry SET is_active = false WHERE dataset_type = ?",
                    [dataset_type],
                )
            db.execute(
                """
                INSERT INTO dataset_registry (
                    dataset_id, display_name, source_file, dataset_type,
                    file_size_bytes, row_count, laundering_count,
                    laundering_rate, date_min, date_max, md5_fingerprint,
                    is_active, notes, column_map, schema_detected,
                    workspace_schema, table_name, protected
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS JSON),
                          ?, ?, ?, false)
                """,
                [
                    dataset_id,
                    display_name,
                    source_file,
                    dataset_type,
                    file_size_bytes,
                    row_count,
                    laundering_count,
                    rate,
                    date_min,
                    date_max,
                    md5_fingerprint,
                    dataset_type in {"primary", "knowledge"},
                    "Uploaded through governed analyst import",
                    json.dumps(inspection.column_map),
                    inspection.schema_name,
                    schema,
                    table_name,
                ],
            )
            db.execute("COMMIT")
            registry_transaction = False
            return result
        except Exception:
            if registry_transaction:
                db.execute("ROLLBACK")
            db.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            raise
    finally:
        if own_conn:
            db.close()


def activate_dataset(
    dataset_id: str,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> DatasetSwitchResult | None:
    """Activate a governed dataset while serializing registry mutations."""
    with _REGISTRY_LOCK:
        return _activate_dataset(dataset_id, conn)


def _activate_dataset(
    dataset_id: str,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> DatasetSwitchResult | None:
    from agent.models import DatasetSwitchResult

    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_dataset_registry(db)
    try:
        row = db.execute(
            "SELECT dataset_type, row_count FROM dataset_registry WHERE dataset_id = ?",
            [dataset_id],
        ).fetchone()
        if row is None:
            return None
        if row[0] == "kyc":
            raise ValueError("KYC enrichment datasets are linked, not activated")
        previous = db.execute(
            """
            SELECT dataset_id FROM dataset_registry
            WHERE dataset_type = ? AND is_active = true
            LIMIT 1
            """,
            [row[0]],
        ).fetchone()
        db.execute("BEGIN TRANSACTION")
        try:
            db.execute(
                "UPDATE dataset_registry SET is_active = false WHERE dataset_type = ?",
                [row[0]],
            )
            db.execute(
                "UPDATE dataset_registry SET is_active = true WHERE dataset_id = ?",
                [dataset_id],
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        return DatasetSwitchResult(
            previous_dataset_id=previous[0] if previous else None,
            active_dataset_id=dataset_id,
            row_count=int(row[1]),
            message=f"{dataset_id} is now the active {row[0]} dataset",
        )
    finally:
        if own_conn:
            db.close()


def delete_dataset(
    dataset_id: str,
    conn: duckdb.DuckDBPyConnection | None = None,
    *,
    remove_source_file: bool = True,
) -> bool:
    """Delete an inactive uploaded workspace under the registry write lock."""
    with _REGISTRY_LOCK:
        return _delete_dataset(
            dataset_id,
            conn,
            remove_source_file=remove_source_file,
        )


def _delete_dataset(
    dataset_id: str,
    conn: duckdb.DuckDBPyConnection | None = None,
    *,
    remove_source_file: bool = True,
) -> bool:
    own_conn = conn is None
    db = conn or get_db_connection()
    ensure_dataset_registry(db)
    try:
        row = db.execute(
            """
            SELECT workspace_schema, is_active, protected,
                   md5_fingerprint, source_file
            FROM dataset_registry WHERE dataset_id = ?
            """,
            [dataset_id],
        ).fetchone()
        if row is None:
            return False
        if row[2]:
            raise ValueError("Built-in governed datasets cannot be deleted")
        if row[1]:
            raise ValueError("Activate another dataset before deletion")
        schema = row[0]
        if not _IDENTIFIER.fullmatch(schema) or schema == "main":
            raise ValueError("Unsafe dataset workspace identifier")
        db.execute("BEGIN TRANSACTION")
        try:
            db.execute("DELETE FROM dataset_registry WHERE dataset_id = ?", [dataset_id])
            db.execute(f'DROP SCHEMA "{schema}" CASCADE')
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        from config import UPLOAD_DIR

        if remove_source_file:
            suffix = Path(row[4] or "").suffix.lower()
            stored = (UPLOAD_DIR / f"{row[3]}{suffix}").resolve()
            upload_root = UPLOAD_DIR.resolve()
            if stored.is_relative_to(upload_root) and stored.exists():
                stored.unlink()
        return True
    finally:
        if own_conn:
            db.close()
