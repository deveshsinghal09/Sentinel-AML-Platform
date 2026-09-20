from __future__ import annotations

import pandas as pd
import pytest

from tools.aggregation import run_aggregation


def _transactions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "from_account": ["A", "A", "A", "B", "B"],
            "to_account": ["X", "Y", "X", "Z", "Z"],
            "amount_paid": [9_000, 9_500, 12_000, 1_000, 2_000],
            "timestamp": pd.to_datetime(
                [
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-03",
                    "2026-01-01",
                    "2026-01-02",
                ]
            ),
        }
    )


def test_threshold_aggregation_groups_and_filters_before_counting():
    result = run_aggregation(
        _transactions(),
        min_count=2,
        max_amount=10_000,
    )

    assert result.total_groups == 2
    assert [row.entity_id for row in result.rows] == ["A", "B"]
    assert result.rows[0].txn_count == 2
    assert result.rows[0].total_amount == 18_500
    assert result.rows[0].distinct_counterparties == 2


def test_threshold_aggregation_returns_empty_structured_result():
    result = run_aggregation(
        _transactions(),
        min_count=10,
        max_amount=10_000,
    )
    assert result.total_groups == 0
    assert result.rows == []
    assert result.filter_applied["min_count"] == 10


def test_threshold_aggregation_rejects_unapproved_group_field():
    with pytest.raises(ValueError, match="unsupported aggregation group"):
        run_aggregation(_transactions(), group_by="payment_format")
