from __future__ import annotations

from datetime import datetime

import duckdb
import pytest

from tools.dataset_store import (
    activate_dataset,
    active_dataset,
    initialize_dataset_registry,
    resolve_transaction_table,
)


def _insert_dataset(
    connection,
    dataset_id,
    *,
    schema,
    active=False,
    protected=False,
):
    connection.execute(
        """
        INSERT INTO dataset_registry (
            dataset_id, display_name, dataset_type, row_count,
            ingested_at, is_active, column_map, workspace_schema,
            table_name, protected
        ) VALUES (?, ?, 'primary', 10, ?, ?, CAST('{}' AS JSON), ?, ?, ?)
        """,
        [
            dataset_id,
            f"Dataset {dataset_id}",
            datetime(2026, 7, 26),
            active,
            schema,
            "transactions",
            protected,
        ],
    )


def test_activation_switches_exactly_one_primary_workspace():
    connection = duckdb.connect(":memory:")
    initialize_dataset_registry(connection)
    _insert_dataset(connection, "ds_first", schema="ds_first", active=True)
    _insert_dataset(connection, "ds_second", schema="ds_second")

    result = activate_dataset("ds_second", connection)
    active = active_dataset(conn=connection)
    count = connection.execute(
        """
        SELECT count(*) FROM dataset_registry
        WHERE dataset_type = 'primary' AND is_active
        """
    ).fetchone()[0]

    assert result.previous_dataset_id == "ds_first"
    assert result.active_dataset_id == "ds_second"
    assert active is not None and active.dataset_id == "ds_second"
    assert count == 1


def test_workspace_identifier_injection_is_rejected_before_query_use():
    connection = duckdb.connect(":memory:")
    initialize_dataset_registry(connection)
    _insert_dataset(
        connection,
        "ds_unsafe",
        schema='main"; DROP TABLE dataset_registry; --',
        active=True,
    )

    with pytest.raises(ValueError, match="Unsafe dataset workspace identifier"):
        resolve_transaction_table(connection, "ds_unsafe")

    assert connection.execute(
        "SELECT count(*) FROM dataset_registry"
    ).fetchone()[0] == 1


def test_unknown_dataset_does_not_fall_back_to_active_evidence():
    connection = duckdb.connect(":memory:")
    initialize_dataset_registry(connection)
    _insert_dataset(connection, "ds_active", schema="ds_active", active=True)

    with pytest.raises(ValueError, match="Dataset not found"):
        resolve_transaction_table(connection, "ds_missing")
