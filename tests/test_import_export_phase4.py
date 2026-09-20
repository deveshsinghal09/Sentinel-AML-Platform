from __future__ import annotations

import csv
import io

import duckdb
import pandas as pd
import pytest

from agent.models import (
    AgentResponse,
    ExecutionStep,
    FlaggedEntity,
    IntentFilters,
    IntentResult,
    PlanResult,
    SummaryStats,
)
from tools.data_loader import _CREATE_DDL
from tools.dataset_store import (
    activate_dataset,
    delete_dataset,
    list_datasets,
    register_uploaded_dataset,
    resolve_transaction_table,
)
from tools.exporter import (
    export_entities_csv,
    export_entities_xlsx,
    export_investigation_md,
    export_investigation_pdf,
    export_sar_pdf,
    export_sar_txt,
)
from tools.importer import detect_schema, inspect_upload


def workspace_connection() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    conn.execute(_CREATE_DDL)
    conn.execute(
        """
        INSERT INTO transactions VALUES (
            '2022-09-01 00:00:00', '001', 'SEED-A', '002', 'SEED-B',
            100, 'USD', 100, 'USD', 'ACH', 0, '2022-09-01', 100
        )
        """
    )
    return conn


def write_generic_csv(path, rows: int = 100):
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=rows, freq="h"),
            "sender_id": [f"A-{index % 5}" for index in range(rows)],
            "receiver_id": [f"B-{index % 7}" for index in range(rows)],
            "amount": [100 + index for index in range(rows)],
            "currency": ["USD"] * rows,
            "payment_type": ["ACH"] * rows,
            "is_laundering": [1 if index == 3 else 0 for index in range(rows)],
        }
    )
    frame.to_csv(path, index=False)


def test_generic_schema_detection_and_isolated_workspace_lifecycle(tmp_path):
    path = tmp_path / "bank-export.csv"
    write_generic_csv(path)
    inspection = inspect_upload(path)
    assert inspection.schema_name == "generic_transactions"
    assert inspection.column_map["from_account"] == "sender_id"

    conn = workspace_connection()
    result = register_uploaded_dataset(
        path=path,
        display_name="Bank export",
        dataset_type="primary",
        md5_fingerprint="a" * 32,
        file_size_bytes=path.stat().st_size,
        conn=conn,
    )
    assert result.row_count == 100
    assert result.eda_summary["laundering_count"] == 1
    datasets = list_datasets(conn)
    uploaded = next(item for item in datasets if item.dataset_id == result.dataset_id)
    assert uploaded.is_active
    table = resolve_transaction_table(conn)
    assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 100

    with pytest.raises(ValueError, match="already registered"):
        register_uploaded_dataset(
            path=path,
            display_name="Duplicate",
            dataset_type="primary",
            md5_fingerprint="a" * 32,
            file_size_bytes=path.stat().st_size,
            conn=conn,
        )
    with pytest.raises(ValueError, match="Activate another"):
        delete_dataset(result.dataset_id, conn)
    activate_dataset("ibm-hi-small-v1", conn)
    assert delete_dataset(result.dataset_id, conn)


def test_schema_rejects_unmapped_and_invalid_amounts(tmp_path):
    schema, mapping = detect_schema(pd.DataFrame({"foo": ["x"], "bar": ["y"]}))
    assert schema == "unmapped"
    assert mapping == {}

    path = tmp_path / "invalid.csv"
    write_generic_csv(path)
    frame = pd.read_csv(path)
    frame.loc[0, "amount"] = -1
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="positive-amount"):
        register_uploaded_dataset(
            path=path,
            display_name="Invalid",
            dataset_type="primary",
            md5_fingerprint="b" * 32,
            file_size_bytes=path.stat().st_size,
            conn=workspace_connection(),
        )


def sample_response() -> AgentResponse:
    entity = FlaggedEntity(
        entity_id="ACC-42",
        risk_score=0.82,
        risk_label="high",
        escalation_action="report",
        rule_flags=["structuring"],
        explanation="Repeated near-threshold transfers.",
        sar_draft="Review repeated transfers below the reporting threshold.",
        citation="31 U.S.C. 5324",
    )
    return AgentResponse(
        investigation_id="INV-TEST",
        dataset_id="ds_test",
        dataset_name="Test bank",
        query="Find structuring",
        intent=IntentResult(
            intent="pattern_search",
            pattern_type="structuring",
            filters=IntentFilters(),
            entities=[],
            require_ml=True,
            require_graph=False,
            require_eda=False,
        ),
        plan=PlanResult(steps=["data_loader"], skipped=[], reasoning="Targeted"),
        execution_trace=[
            ExecutionStep(
                tool="data_loader",
                status="run",
                duration_ms=1.2,
                reason="Loaded bounded evidence",
            )
        ],
        top_entities=[entity],
        summary_stats=SummaryStats(total_analyzed=100, flagged=1, high_risk=1),
    )


def test_regulatory_exports_have_valid_headers_and_human_review_notice():
    response = sample_response()
    entity = response.top_entities[0]

    csv_bytes = export_entities_csv(response.top_entities)
    rows = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"))))
    assert rows[0]["entity_id"] == "ACC-42"
    assert rows[0]["rule_flags"] == "structuring"
    assert export_entities_xlsx(response).startswith(b"PK")
    assert export_sar_pdf(entity).startswith(b"%PDF")
    assert export_investigation_pdf(response).startswith(b"%PDF")
    sar = export_sar_txt(entity).decode()
    assert "DRAFT ONLY" in sar
    assert "qualified human reviewer" in sar
    report = export_investigation_md(response).decode()
    assert "ds_test" in report
    assert "Human review is required" in report
