"""
test_data_loader.py — Phase 1 unit tests.

Run with: pytest tests/test_data_loader.py -v

These tests use a small synthetic DataFrame injected directly into DuckDB
(an in-memory DB) so they run fast without requiring the real IBM CSV.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest
import pandas as pd
import duckdb
from datetime import date, timedelta

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# We'll monkey-patch get_db_connection to use in-memory DuckDB for tests
import tools.data_loader as dl

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def in_memory_conn():
    """Return an in-memory DuckDB connection pre-populated with synthetic data."""
    conn = duckdb.connect(":memory:")
    conn.execute(dl._CREATE_DDL)

    rows = []
    base_date = date(2023, 1, 1)
    for i in range(100):
        d = base_date + timedelta(days=i % 30)
        rows.append({
            "timestamp": f"{d} 10:{i%60:02d}:00",
            "from_bank": f"BANK_{i%5}",
            "from_account": f"ACC_{i%10}",
            "to_bank": f"BANK_{(i+1)%5}",
            "to_account": f"ACC_{(i+1)%10}",
            "amount_received": 9000.0 + (i % 500),
            "receiving_currency": "USD",
            "amount_paid": 9000.0 + (i % 500),
            "paying_currency": "USD",
            "payment_format": "Wire" if i % 2 == 0 else "ACH",
            "is_laundering": 1 if i < 5 else 0,
            "txn_date": str(d),
            "amount_usd": 9000.0 + (i % 500),
        })
    df = pd.DataFrame(rows)
    conn.execute(f"INSERT INTO {dl._TABLE_NAME} SELECT * FROM df")
    return conn


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_table_exists(in_memory_conn):
    assert dl._table_exists(in_memory_conn)


def test_row_count(in_memory_conn):
    assert dl._row_count(in_memory_conn) == 100


def test_load_no_filter_returns_all(in_memory_conn):
    df = dl.load(conn=in_memory_conn)
    assert len(df) == 100


def test_load_date_range(in_memory_conn):
    df = dl.load(date_range=("2023-01-01", "2023-01-15"), conn=in_memory_conn)
    # All txn_dates should be ≤ 2023-01-15
    assert all(pd.to_datetime(df["txn_date"]).dt.date <= date(2023, 1, 15))
    assert len(df) > 0


def test_load_entity_id(in_memory_conn):
    df = dl.load(entity_id="ACC_0", conn=in_memory_conn)
    assert all(
        (df["from_account"] == "ACC_0") | (df["to_account"] == "ACC_0")
    )
    assert len(df) > 0


def test_load_is_laundering_filter(in_memory_conn):
    df = dl.load(is_laundering=1, conn=in_memory_conn)
    assert len(df) == 5
    assert all(df["is_laundering"] == 1)


def test_load_amount_filter(in_memory_conn):
    df = dl.load(min_amount=9400.0, conn=in_memory_conn)
    assert all(df["amount_paid"] >= 9400.0)


def test_load_payment_format_filter(in_memory_conn):
    df = dl.load(payment_format="Wire", conn=in_memory_conn)
    assert all(df["payment_format"] == "Wire")


def test_load_limit(in_memory_conn):
    df = dl.load(limit=10, conn=in_memory_conn)
    assert len(df) == 10


def test_load_combined_filters(in_memory_conn):
    df = dl.load(
        date_range=("2023-01-01", "2023-01-10"),
        payment_format="Wire",
        conn=in_memory_conn,
    )
    assert all(df["payment_format"] == "Wire")
    assert all(pd.to_datetime(df["txn_date"]).dt.date <= date(2023, 1, 10))


def test_summary_stats_keys(in_memory_conn):
    stats = dl.get_summary_stats(conn=in_memory_conn)
    expected_keys = {
        "total_rows", "laundering_count", "laundering_rate_pct",
        "date_min", "date_max", "unique_from_accounts",
        "unique_to_accounts", "unique_banks",
    }
    assert expected_keys.issubset(set(stats.keys()))
    assert stats["total_rows"] == 100
    assert stats["laundering_count"] == 5
    assert round(stats["laundering_rate_pct"], 1) == 5.0


def test_ingest_csv_accepts_actual_payment_currency_header(tmp_path):
    csv_path = tmp_path / "hi_small.csv"
    csv_path.write_text(
        "Timestamp,From Bank,Account,To Bank,Account,Amount Received,"
        "Receiving Currency,Amount Paid,Payment Currency,Payment Format,"
        "Is Laundering\n"
        "2022/09/01 00:20,010,8000EBD30,011,8000F5340,10.5,"
        "US Dollar,10.5,US Dollar,Cheque,1\n",
        encoding="utf-8",
    )
    conn = duckdb.connect(":memory:")
    try:
        assert dl.ingest_csv(
            csv_path=csv_path,
            chunksize=1,
            conn=conn,
        ) == 1
        row = conn.execute(
            "SELECT from_bank, paying_currency, is_laundering "
            "FROM transactions"
        ).fetchone()
        assert row == ("010", "US Dollar", 1)
    finally:
        conn.close()


def test_ingest_saml_keeps_positives_and_samples_normals(tmp_path):
    csv_path = tmp_path / "saml.csv"
    rows = [
        "Time,Date,Sender_account,Receiver_account,Amount,"
        "Payment_currency,Received_currency,Sender_bank_location,"
        "Receiver_bank_location,Payment_type,Is_laundering,"
        "Laundering_type"
    ]
    for i in range(8):
        is_laundering = 1 if i in {1, 6} else 0
        typology = "Structuring" if is_laundering else "Normal_Group"
        rows.append(
            f"10:35:{i:02d},2022-10-07,S{i},R{i},{100 + i},"
            f"GBP,GBP,UK,UK,ACH,{is_laundering},{typology}"
        )
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    conn = duckdb.connect(":memory:")
    try:
        count = dl.ingest_saml_knowledge(
            saml_path=csv_path,
            normal_sample_size=3,
            chunksize=2,
            random_seed=7,
            conn=conn,
        )
        assert count == 5
        stats = dl.get_saml_summary_stats(conn=conn)
        assert stats["laundering_count"] == 2
        assert stats["normal_sample_count"] == 3
        assert stats["typology_count"] == 2
        assert not dl._table_exists(conn, dl._TABLE_NAME)
    finally:
        conn.close()
