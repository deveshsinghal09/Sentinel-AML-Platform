from __future__ import annotations

import pytest

from agent.knowledge import get_knowledge
from tools.data_loader import (
    _SAML_TABLE_NAME,
    _table_exists,
    get_db_connection,
    get_saml_summary_stats,
)
from tools.rule_engine import validate_rules_against_saml


pytestmark = pytest.mark.integration


@pytest.mark.requires_data
def test_saml_knowledge_table_exists():
    conn = get_db_connection()
    try:
        assert _table_exists(conn, _SAML_TABLE_NAME)
    finally:
        conn.close()


@pytest.mark.requires_data
def test_saml_knowledge_has_positive_rows():
    stats = get_saml_summary_stats()
    assert stats["total_rows"] > 0
    assert stats["laundering_count"] > 0


@pytest.fixture(scope="module")
def rule_metrics():
    return validate_rules_against_saml()


@pytest.mark.requires_data
def test_rule_engine_recall_on_saml_structuring(rule_metrics):
    assert "Structuring" in rule_metrics
    assert {"total", "recall"}.issubset(rule_metrics["Structuring"])
    assert 0 <= rule_metrics["Structuring"]["recall"] <= 1


@pytest.mark.requires_data
def test_rule_engine_recall_on_saml_fan_in(rule_metrics):
    assert rule_metrics["Fan_In"]["total"] > 0


def test_knowledge_bm25_returns_structuring_for_structuring_query():
    results = get_knowledge().lookup("structuring CTR avoidance", top_k=1)
    assert len(results) == 1
    assert results[0]["bm25_score"] > 0
