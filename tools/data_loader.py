"""Memory-safe ingestion and filtered access for the AML datasets.

The two source datasets deliberately remain separate:

* ``transactions`` contains HI-Small transactions used for detection.
* ``saml_knowledge`` contains every labelled SAML-D laundering row plus a
  deterministic sample of normal rows used for calibration and validation.

Both ingests stream CSV chunks and publish a completed staging table
atomically, so a failed ingest cannot leave a partially populated live table.
"""
from __future__ import annotations

import hashlib
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

import duckdb
import numpy as np
import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CSV_PATH, DB_PATH, MAX_QUERY_ROWS, SAML_D_PATH


_TABLE_NAME = "transactions"
_SAML_TABLE_NAME = "saml_knowledge"
_DEFAULT_CHUNK_SIZE = 100_000
_DEFAULT_NORMAL_SAMPLE_SIZE = 50_000
_SAML_SAMPLE_SEED = 42

_COL_MAP: dict[str, str] = {
    "Timestamp": "timestamp",
    "From Bank": "from_bank",
    "Account": "from_account",
    "To Bank": "to_bank",
    "Account.1": "to_account",
    "Amount Received": "amount_received",
    "Receiving Currency": "receiving_currency",
    "Amount Paid": "amount_paid",
    # IBM AML exports use this heading. Keep the older variant for
    # compatibility with alternate releases of the dataset.
    "Payment Currency": "paying_currency",
    "Paying Currency": "paying_currency",
    "Payment Format": "payment_format",
    "Is Laundering": "is_laundering",
}

_TRANSACTION_COLUMNS = [
    "timestamp",
    "from_bank",
    "from_account",
    "to_bank",
    "to_account",
    "amount_received",
    "receiving_currency",
    "amount_paid",
    "paying_currency",
    "payment_format",
    "is_laundering",
    "txn_date",
    "amount_usd",
]

_SAML_SOURCE_COLUMNS = {
    "Time",
    "Date",
    "Sender_account",
    "Receiver_account",
    "Amount",
    "Payment_currency",
    "Received_currency",
    "Sender_bank_location",
    "Receiver_bank_location",
    "Payment_type",
    "Is_laundering",
    "Laundering_type",
}

_SAML_COLUMNS = [
    "timestamp",
    "txn_date",
    "from_account",
    "to_account",
    "amount",
    "payment_currency",
    "received_currency",
    "from_country",
    "to_country",
    "payment_format",
    "is_laundering",
    "laundering_type",
]


def _transaction_ddl(table_name: str = _TABLE_NAME) -> str:
    return f"""
CREATE TABLE {table_name} (
    timestamp           TIMESTAMP,
    from_bank           VARCHAR,
    from_account        VARCHAR,
    to_bank             VARCHAR,
    to_account          VARCHAR,
    amount_received     DOUBLE,
    receiving_currency  VARCHAR,
    amount_paid         DOUBLE,
    paying_currency     VARCHAR,
    payment_format      VARCHAR,
    is_laundering       INTEGER,
    txn_date            DATE,
    amount_usd          DOUBLE
);
"""


def _saml_ddl(table_name: str = _SAML_TABLE_NAME) -> str:
    return f"""
CREATE TABLE {table_name} (
    timestamp           TIMESTAMP,
    txn_date            DATE,
    from_account        VARCHAR,
    to_account          VARCHAR,
    amount              DOUBLE,
    payment_currency    VARCHAR,
    received_currency   VARCHAR,
    from_country        VARCHAR,
    to_country          VARCHAR,
    payment_format      VARCHAR,
    is_laundering       INTEGER,
    laundering_type     VARCHAR
);
"""


# Kept public for the existing in-memory unit-test fixture.
_CREATE_DDL = _transaction_ddl()


def get_db_connection() -> duckdb.DuckDBPyConnection:
    """Return a read-write connection to the project DuckDB database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(DB_PATH))
    connection.execute("SET TimeZone = 'UTC'")
    return connection


def _csv_fingerprint(csv_path: Path) -> str:
    """Return a quick fingerprint of a source file."""
    digest = hashlib.md5()
    with csv_path.open("rb") as source:
        digest.update(source.read(65_536))
    return digest.hexdigest()


def _table_exists(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = _TABLE_NAME,
) -> bool:
    result = conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
        [table_name],
    ).fetchone()
    return bool(result and result[0] > 0)


def _row_count(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = _TABLE_NAME,
) -> int:
    # table_name is always an internal constant or a test-only identifier.
    return int(conn.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0])


def _clean_strings(df: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        df[column] = df[column].astype("string").fillna("").str.strip()


def _normalise_transaction_chunk(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert an HI-Small CSV chunk to the canonical transaction schema."""
    df = raw.rename(columns=_COL_MAP).copy()
    missing = [column for column in _TRANSACTION_COLUMNS[:11] if column not in df]
    if missing:
        raise ValueError(
            "HI-Small CSV is missing required columns after normalisation: "
            + ", ".join(missing)
        )

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["txn_date"] = df["timestamp"].dt.date
    df["amount_received"] = pd.to_numeric(
        df["amount_received"], errors="coerce"
    )
    df["amount_paid"] = pd.to_numeric(df["amount_paid"], errors="coerce")
    df["amount_usd"] = df["amount_paid"]
    df["is_laundering"] = (
        pd.to_numeric(df["is_laundering"], errors="coerce")
        .fillna(0)
        .astype("int8")
    )
    _clean_strings(
        df,
        [
            "from_bank",
            "from_account",
            "to_bank",
            "to_account",
            "receiving_currency",
            "paying_currency",
            "payment_format",
        ],
    )
    return df[_TRANSACTION_COLUMNS]


def _normalise_saml_rows(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert selected SAML-D rows to the separate knowledge schema."""
    missing = sorted(_SAML_SOURCE_COLUMNS.difference(raw.columns))
    if missing:
        raise ValueError(
            "SAML-D CSV is missing required columns: " + ", ".join(missing)
        )

    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                raw["Date"].astype(str) + " " + raw["Time"].astype(str),
                errors="coerce",
            ),
            "from_account": raw["Sender_account"],
            "to_account": raw["Receiver_account"],
            "amount": pd.to_numeric(raw["Amount"], errors="coerce"),
            "payment_currency": raw["Payment_currency"],
            "received_currency": raw["Received_currency"],
            "from_country": raw["Sender_bank_location"],
            "to_country": raw["Receiver_bank_location"],
            "payment_format": raw["Payment_type"],
            "is_laundering": (
                pd.to_numeric(raw["Is_laundering"], errors="coerce")
                .fillna(0)
                .astype("int8")
            ),
            "laundering_type": raw["Laundering_type"],
        }
    )
    df.insert(1, "txn_date", df["timestamp"].dt.date)
    _clean_strings(
        df,
        [
            "from_account",
            "to_account",
            "payment_currency",
            "received_currency",
            "from_country",
            "to_country",
            "payment_format",
            "laundering_type",
        ],
    )
    return df[_SAML_COLUMNS]


def _insert_frame(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    frame: pd.DataFrame,
    registration_name: str,
) -> None:
    conn.register(registration_name, frame)
    try:
        columns = ", ".join(frame.columns)
        conn.execute(
            f"INSERT INTO {table_name} ({columns}) "
            f"SELECT {columns} FROM {registration_name}"
        )
    finally:
        conn.unregister(registration_name)


def _publish_staging_table(
    conn: duckdb.DuckDBPyConnection,
    staging_name: str,
    table_name: str,
) -> None:
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute(f"ALTER TABLE {staging_name} RENAME TO {table_name}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def ingest_csv(
    csv_path: Optional[Path] = None,
    force: bool = False,
    chunksize: int = _DEFAULT_CHUNK_SIZE,
    conn: Optional[duckdb.DuckDBPyConnection] = None,
) -> int:
    """Stream the HI-Small transaction CSV into ``transactions``.

    The input is read as strings so bank and account identifiers retain
    leading zeroes. Numeric and date columns are converted per chunk.
    """
    source_path = Path(csv_path or CSV_PATH)
    if not source_path.exists():
        raise FileNotFoundError(f"HI-Small CSV not found at {source_path}")
    if chunksize <= 0:
        raise ValueError("chunksize must be greater than zero")

    own_conn = conn is None
    db = conn or get_db_connection()
    staging_name = "_transactions_ingest"
    try:
        if _table_exists(db, _TABLE_NAME) and not force:
            count = _row_count(db, _TABLE_NAME)
            logger.info(
                "Table '{}' already has {:,} rows; skipping HI-Small ingest",
                _TABLE_NAME,
                count,
            )
            return count

        db.execute(f"DROP TABLE IF EXISTS {staging_name}")
        db.execute(_transaction_ddl(staging_name))

        total_rows = 0
        laundering_rows = 0
        for chunk_number, raw_chunk in enumerate(
            pd.read_csv(
                source_path,
                dtype=str,
                keep_default_na=False,
                low_memory=False,
                chunksize=chunksize,
            ),
            start=1,
        ):
            chunk = _normalise_transaction_chunk(raw_chunk)
            _insert_frame(db, staging_name, chunk, "_ibm_chunk")
            total_rows += len(chunk)
            laundering_rows += int(chunk["is_laundering"].sum())
            logger.info(
                "HI-Small chunk {} complete ({:,} rows total)",
                chunk_number,
                total_rows,
            )

        if total_rows == 0:
            raise ValueError(f"HI-Small CSV at {source_path} contains no rows")

        _publish_staging_table(db, staging_name, _TABLE_NAME)
        rate = laundering_rows / total_rows * 100
        logger.success(
            "Ingested {:,} HI-Small rows; {:,} laundering ({:.4f}%)",
            total_rows,
            laundering_rows,
            rate,
        )
        return total_rows
    except Exception:
        db.execute(f"DROP TABLE IF EXISTS {staging_name}")
        raise
    finally:
        if own_conn:
            db.close()


def ingest_saml_knowledge(
    saml_path: Optional[Path] = None,
    force: bool = False,
    normal_sample_size: int = _DEFAULT_NORMAL_SAMPLE_SIZE,
    chunksize: int = _DEFAULT_CHUNK_SIZE,
    random_seed: int = _SAML_SAMPLE_SEED,
    conn: Optional[duckdb.DuckDBPyConnection] = None,
) -> int:
    """Build the compact SAML-D calibration table without loading 9.5M rows.

    Every positive row is retained. Normal rows receive deterministic random
    priority keys, and only the globally smallest ``normal_sample_size`` keys
    are retained. This is a uniform reservoir sample over the complete file.
    """
    source_path = Path(saml_path or SAML_D_PATH)
    if not source_path.exists():
        raise FileNotFoundError(f"SAML-D CSV not found at {source_path}")
    if normal_sample_size < 0:
        raise ValueError("normal_sample_size cannot be negative")
    if chunksize <= 0:
        raise ValueError("chunksize must be greater than zero")

    own_conn = conn is None
    db = conn or get_db_connection()
    staging_name = "_saml_knowledge_ingest"
    try:
        if _table_exists(db, _SAML_TABLE_NAME) and not force:
            count = _row_count(db, _SAML_TABLE_NAME)
            logger.info(
                "Table '{}' already has {:,} rows; skipping SAML-D ingest",
                _SAML_TABLE_NAME,
                count,
            )
            return count

        rng = np.random.default_rng(random_seed)
        positive_chunks: list[pd.DataFrame] = []
        normal_reservoir: Optional[pd.DataFrame] = None
        typology_counts: Counter[str] = Counter()
        source_rows = 0
        positive_rows = 0

        for chunk_number, raw_chunk in enumerate(
            pd.read_csv(
                source_path,
                dtype=str,
                keep_default_na=False,
                low_memory=False,
                chunksize=chunksize,
            ),
            start=1,
        ):
            missing = sorted(_SAML_SOURCE_COLUMNS.difference(raw_chunk.columns))
            if missing:
                raise ValueError(
                    "SAML-D CSV is missing required columns: " + ", ".join(missing)
                )

            labels = pd.to_numeric(
                raw_chunk["Is_laundering"], errors="coerce"
            ).fillna(0).astype("int8")
            typology_counts.update(raw_chunk["Laundering_type"].astype(str))

            positives = raw_chunk.loc[labels.eq(1)].copy()
            if not positives.empty:
                positive_chunks.append(positives)
                positive_rows += len(positives)

            if normal_sample_size:
                normals = raw_chunk.loc[labels.eq(0)].copy()
                if not normals.empty:
                    normals["_sample_key"] = rng.random(len(normals))
                    if normal_reservoir is None:
                        candidates = normals
                    else:
                        candidates = pd.concat(
                            [normal_reservoir, normals],
                            ignore_index=True,
                        )
                    normal_reservoir = candidates.nsmallest(
                        normal_sample_size,
                        "_sample_key",
                    ).copy()

            source_rows += len(raw_chunk)
            logger.info(
                "SAML-D chunk {} scanned ({:,} source rows, {:,} positives)",
                chunk_number,
                source_rows,
                positive_rows,
            )

        selected_parts = positive_chunks
        if normal_reservoir is not None:
            selected_parts = [
                *selected_parts,
                normal_reservoir.drop(columns="_sample_key"),
            ]
        if not selected_parts:
            raise ValueError(f"SAML-D CSV at {source_path} contains no usable rows")

        selected = pd.concat(selected_parts, ignore_index=True)
        knowledge_rows = _normalise_saml_rows(selected)

        db.execute(f"DROP TABLE IF EXISTS {staging_name}")
        db.execute(_saml_ddl(staging_name))
        _insert_frame(db, staging_name, knowledge_rows, "_saml_rows")
        _publish_staging_table(db, staging_name, _SAML_TABLE_NAME)

        normal_rows = len(knowledge_rows) - positive_rows
        logger.success(
            "Ingested {:,} SAML-D knowledge rows: {:,} positives + "
            "{:,} sampled normals (scanned {:,} source rows)",
            len(knowledge_rows),
            positive_rows,
            normal_rows,
            source_rows,
        )
        logger.info(
            "SAML-D source contains {} distinct typology labels",
            len(typology_counts),
        )
        return len(knowledge_rows)
    except Exception:
        db.execute(f"DROP TABLE IF EXISTS {staging_name}")
        raise
    finally:
        if own_conn:
            db.close()


def load(
    date_range: Optional[tuple[str, str]] = None,
    entity_id: Optional[str] = None,
    from_bank: Optional[str] = None,
    to_bank: Optional[str] = None,
    payment_format: Optional[str] = None,
    currency: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    is_laundering: Optional[int] = None,
    limit: Optional[int] = None,
    dataset_id: Optional[str] = None,
    conn: Optional[duckdb.DuckDBPyConnection] = None,
) -> pd.DataFrame:
    """Return a predicate-pushed slice from the selected primary dataset."""
    if date_range is not None and date_range[0] > date_range[1]:
        raise ValueError("date_range start must not be after its end")
    if min_amount is not None and min_amount < 0:
        raise ValueError("min_amount cannot be negative")
    if max_amount is not None and max_amount < 0:
        raise ValueError("max_amount cannot be negative")
    if (
        min_amount is not None
        and max_amount is not None
        and min_amount > max_amount
    ):
        raise ValueError("min_amount must not exceed max_amount")
    if is_laundering not in {None, 0, 1}:
        raise ValueError("is_laundering must be 0, 1, or None")
    if limit is not None and not 1 <= limit <= MAX_QUERY_ROWS:
        raise ValueError(f"limit must be between 1 and {MAX_QUERY_ROWS}")

    own_conn = conn is None
    db = conn or get_db_connection()
    try:
        from tools.dataset_store import resolve_transaction_table

        table_name = resolve_transaction_table(db, dataset_id)
        predicates: list[str] = []
        params: list[object] = []

        if date_range is not None:
            start, end = date_range
            predicates.append("txn_date BETWEEN ? AND ?")
            params.extend([start, end])
        if entity_id is not None:
            predicates.append("(from_account = ? OR to_account = ?)")
            params.extend([str(entity_id), str(entity_id)])
        if from_bank is not None:
            predicates.append("from_bank = ?")
            params.append(str(from_bank))
        if to_bank is not None:
            predicates.append("to_bank = ?")
            params.append(str(to_bank))
        if payment_format is not None:
            predicates.append("payment_format = ?")
            params.append(str(payment_format))
        if currency is not None:
            predicates.append(
                "(paying_currency = ? OR receiving_currency = ?)"
            )
            params.extend([str(currency), str(currency)])
        if min_amount is not None:
            predicates.append("amount_paid >= ?")
            params.append(float(min_amount))
        if max_amount is not None:
            predicates.append("amount_paid <= ?")
            params.append(float(max_amount))
        if is_laundering is not None:
            predicates.append("is_laundering = ?")
            params.append(int(is_laundering))

        where_clause = (
            "WHERE " + " AND ".join(predicates) if predicates else ""
        )
        limit_clause = f"LIMIT {limit}" if limit is not None else ""
        sql = f"SELECT * FROM {table_name} {where_clause} {limit_clause}"
        return db.execute(sql, params).df()
    finally:
        if own_conn:
            db.close()


def get_summary_stats(
    dataset_id: Optional[str] = None,
    conn: Optional[duckdb.DuckDBPyConnection] = None,
) -> dict:
    """Return high-level statistics for the primary detection table."""
    own_conn = conn is None
    db = conn or get_db_connection()
    try:
        if dataset_id is None:
            table_name = _TABLE_NAME
        else:
            from tools.dataset_store import resolve_transaction_table

            table_name = resolve_transaction_table(db, dataset_id)
        stats: dict = {}
        queries = {
            "total_rows": f"SELECT count(*) FROM {table_name}",
            "laundering_count": (
                f"SELECT count(*) FROM {table_name} WHERE is_laundering = 1"
            ),
            "date_min": f"SELECT min(txn_date) FROM {table_name}",
            "date_max": f"SELECT max(txn_date) FROM {table_name}",
            "unique_from_accounts": (
                f"SELECT count(DISTINCT from_account) FROM {table_name}"
            ),
            "unique_to_accounts": (
                f"SELECT count(DISTINCT to_account) FROM {table_name}"
            ),
            "unique_banks": (
                f"SELECT count(DISTINCT from_bank) FROM {table_name}"
            ),
            "payment_formats": (
                f"SELECT payment_format, count(*) AS cnt FROM {table_name} "
                "GROUP BY payment_format ORDER BY cnt DESC"
            ),
            "currencies": (
                f"SELECT paying_currency, count(*) AS cnt FROM {table_name} "
                "GROUP BY paying_currency ORDER BY cnt DESC"
            ),
        }
        for key, sql in queries.items():
            result = db.execute(sql).fetchall()
            if key in {"payment_formats", "currencies"}:
                stats[key] = [
                    {"value": row[0], "count": row[1]} for row in result
                ]
            else:
                stats[key] = result[0][0]
        stats["laundering_rate_pct"] = (
            round(
                stats["laundering_count"] / stats["total_rows"] * 100,
                4,
            )
            if stats["total_rows"]
            else 0.0
        )
        return stats
    finally:
        if own_conn:
            db.close()


def get_saml_summary_stats(
    conn: Optional[duckdb.DuckDBPyConnection] = None,
) -> dict:
    """Return counts for the compact SAML-D knowledge table."""
    own_conn = conn is None
    db = conn or get_db_connection()
    try:
        total, positives, normal_rows, typologies = db.execute(
            f"""
            SELECT
                count(*),
                count(*) FILTER (WHERE is_laundering = 1),
                count(*) FILTER (WHERE is_laundering = 0),
                count(DISTINCT laundering_type)
            FROM {_SAML_TABLE_NAME}
            """
        ).fetchone()
        return {
            "total_rows": total,
            "laundering_count": positives,
            "normal_sample_count": normal_rows,
            "typology_count": typologies,
        }
    finally:
        if own_conn:
            db.close()


if __name__ == "__main__":
    from datetime import timedelta

    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.rule("[bold cyan]AML Data Loader - Phase 1")

    console.print("\n[bold]Step 1:[/bold] Ingesting HI-Small...")
    transaction_count = ingest_csv()
    console.print(f"  [green]OK[/green] {transaction_count:,} rows")

    console.print("\n[bold]Step 2:[/bold] Ingesting SAML-D knowledge sample...")
    saml_count = ingest_saml_knowledge()
    console.print(f"  [green]OK[/green] {saml_count:,} rows")

    stats = get_summary_stats()
    saml_stats = get_saml_summary_stats()
    summary = Table("Metric", "Value", header_style="bold magenta")
    for key, value in {
        **{f"HI-Small {key}": value for key, value in stats.items()},
        **{f"SAML-D {key}": value for key, value in saml_stats.items()},
    }.items():
        summary.add_row(
            key,
            str(value[:3]) + " ..." if isinstance(value, list) else str(value),
        )
    console.print(summary)

    date_min = stats["date_min"]
    start = (
        datetime.combine(date_min, datetime.min.time())
        if not isinstance(date_min, datetime)
        else date_min
    )
    end = start + timedelta(days=30)
    filtered = load(
        date_range=(str(date_min), end.strftime("%Y-%m-%d")),
        limit=3,
    )
    console.print("\n[bold]First three rows from the first 30 days:[/bold]")
    console.print(filtered.to_string(index=False))
    console.rule("[bold green]Phase 1 smoke test complete")
