from __future__ import annotations

import pytest

from tools.data_loader import (
    _SAML_TABLE_NAME,
    _table_exists,
    get_db_connection,
    get_saml_summary_stats,
    load,
)


@pytest.mark.requires_data
def test_saml_knowledge_table_exists():
    conn = get_db_connection()
    try:
        assert _table_exists(conn, _SAML_TABLE_NAME)
    finally:
        conn.close()


@pytest.mark.requires_data
def test_get_saml_summary_stats_returns_expected_keys():
    stats = get_saml_summary_stats()
    assert {
        "total_rows",
        "laundering_count",
        "normal_sample_count",
        "typology_count",
    }.issubset(stats)


def test_load_rejects_inverted_date_range():
    with pytest.raises(ValueError, match="start must not be after"):
        load(date_range=("2022-09-18", "2022-09-01"), limit=1)


@pytest.mark.requires_data
def test_load_with_entity_id_returns_matching_rows_only():
    result = load(entity_id="803D95360", limit=100)
    assert len(result) > 0
    assert (
        result["from_account"].eq("803D95360")
        | result["to_account"].eq("803D95360")
    ).all()
