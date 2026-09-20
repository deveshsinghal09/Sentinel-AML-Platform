"""Dedicated grouped threshold aggregation for direct AML analyst questions."""
from __future__ import annotations

from typing import Any

import pandas as pd

from agent.models import AggregationResult, AggregationRow


_ALLOWED_GROUPS = {"from_account", "to_account"}
_ALLOWED_ORDER_FIELDS = {
    "txn_count",
    "total_amount",
    "avg_amount",
    "min_amount",
    "max_amount_val",
    "distinct_counterparties",
}


def _iso(value: Any) -> str:
    timestamp = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(timestamp) else timestamp.isoformat()


def run_aggregation(
    df: pd.DataFrame,
    group_by: str = "from_account",
    min_count: int = 1,
    max_amount: float | None = None,
    min_amount: float | None = None,
    time_window_days: int | None = None,
    order_by: str = "txn_count",
    limit: int = 100,
) -> AggregationResult:
    """Group a query-scoped transaction set and apply explicit thresholds.

    Date-window filtering is normally performed by ``data_loader`` before this
    tool runs. ``time_window_days`` provides a deterministic trailing-window
    fallback for direct callers and is anchored to the newest input timestamp.
    A threshold match is returned as evidence, not automatically labelled as
    suspicious; downstream policy may decide whether it warrants a risk score.
    """
    if group_by not in _ALLOWED_GROUPS:
        raise ValueError(f"unsupported aggregation group: {group_by}")
    if order_by not in _ALLOWED_ORDER_FIELDS:
        raise ValueError(f"unsupported aggregation order field: {order_by}")
    if min_count < 1 or limit < 1:
        raise ValueError("min_count and limit must be greater than zero")

    required = {group_by, "amount_paid", "timestamp", "to_account"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(
            "aggregation input missing required columns: "
            + ", ".join(sorted(missing))
        )

    work = df.copy()
    work["amount_paid"] = pd.to_numeric(
        work["amount_paid"], errors="coerce"
    )
    work["timestamp"] = pd.to_datetime(work["timestamp"], errors="coerce")
    work = work.dropna(subset=[group_by, "amount_paid", "timestamp"])

    if max_amount is not None:
        work = work.loc[work["amount_paid"] <= max_amount]
    if min_amount is not None:
        work = work.loc[work["amount_paid"] >= min_amount]
    if time_window_days is not None:
        if time_window_days < 1:
            raise ValueError("time_window_days must be greater than zero")
        newest = work["timestamp"].max()
        if pd.notna(newest):
            cutoff = newest - pd.Timedelta(days=time_window_days)
            work = work.loc[work["timestamp"] >= cutoff]

    if work.empty:
        return AggregationResult(
            rows=[],
            total_groups=0,
            filter_applied={
                "min_count": min_count,
                "max_amount": max_amount,
                "min_amount": min_amount,
                "time_window_days": time_window_days,
            },
            group_by_field=group_by,
        )

    grouped = (
        work.groupby(group_by, dropna=False)
        .agg(
            txn_count=("amount_paid", "count"),
            total_amount=("amount_paid", "sum"),
            avg_amount=("amount_paid", "mean"),
            min_amount=("amount_paid", "min"),
            max_amount_val=("amount_paid", "max"),
            date_first=("timestamp", "min"),
            date_last=("timestamp", "max"),
            distinct_counterparties=("to_account", "nunique"),
        )
        .reset_index()
    )
    filtered = grouped.loc[grouped["txn_count"] >= min_count]
    ordered = filtered.sort_values(
        [order_by, group_by],
        ascending=[False, True],
        kind="stable",
    ).head(limit)

    rows = [
        AggregationRow(
            entity_id=str(row[group_by]),
            txn_count=int(row["txn_count"]),
            total_amount=float(row["total_amount"]),
            avg_amount=float(row["avg_amount"]),
            min_amount=float(row["min_amount"]),
            max_amount=float(row["max_amount_val"]),
            date_first=_iso(row["date_first"]),
            date_last=_iso(row["date_last"]),
            distinct_counterparties=int(row["distinct_counterparties"]),
        )
        for _, row in ordered.iterrows()
    ]
    return AggregationResult(
        rows=rows,
        total_groups=int(len(filtered)),
        filter_applied={
            "min_count": min_count,
            "max_amount": max_amount,
            "min_amount": min_amount,
            "time_window_days": time_window_days,
        },
        group_by_field=group_by,
    )
