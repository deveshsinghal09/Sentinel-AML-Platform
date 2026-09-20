"""Exploratory summaries and compact Plotly-compatible chart payloads."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _json_scalar(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _amount_series(df: pd.DataFrame) -> pd.Series:
    column = "amount_paid" if "amount_paid" in df else "amount"
    if column not in df:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce").dropna()


def _amount_histogram(amounts: pd.Series, bins: int = 30) -> dict:
    if amounts.empty:
        return {
            "chart_id": "amount_histogram",
            "title": "Transaction amount distribution",
            "data": [],
            "layout": {},
        }

    values = amounts.to_numpy(dtype=float)
    upper = float(np.quantile(values, 0.99))
    lower = float(np.min(values))
    if upper <= lower:
        upper = lower + max(abs(lower) * 0.01, 1.0)
    clipped = values[values <= upper]
    counts, edges = np.histogram(clipped, bins=bins, range=(lower, upper))
    centers = ((edges[:-1] + edges[1:]) / 2).tolist()
    widths = np.diff(edges).tolist()
    overflow = int((values > upper).sum())

    return {
        "chart_id": "amount_histogram",
        "title": "Transaction amount distribution",
        "data": [
            {
                "type": "bar",
                "name": "Transactions",
                "x": [float(value) for value in centers],
                "y": [int(value) for value in counts],
                "width": [float(value) for value in widths],
                "hovertemplate": (
                    "Amount %{x:,.2f}<br>Transactions %{y:,}<extra></extra>"
                ),
            }
        ],
        "layout": {
            "xaxis": {"title": "Amount paid"},
            "yaxis": {"title": "Transaction count"},
            "bargap": 0.02,
        },
        "meta": {
            "displayed_upper_percentile": 0.99,
            "displayed_upper_amount": upper,
            "overflow_count": overflow,
            "note": (
                "The final 1% tail is counted separately so extreme values "
                "do not flatten the visible distribution."
            ),
        },
    }


def _transactions_over_time(df: pd.DataFrame) -> dict:
    if "timestamp" not in df:
        return {
            "chart_id": "transactions_over_time",
            "title": "Transactions over time",
            "data": [],
            "layout": {},
        }
    timestamps = pd.to_datetime(df["timestamp"], errors="coerce").dropna()
    if timestamps.empty:
        dates: list[str] = []
        counts: list[int] = []
    else:
        daily = timestamps.dt.floor("D").value_counts().sort_index()
        dates = [timestamp.date().isoformat() for timestamp in daily.index]
        counts = [int(value) for value in daily.to_numpy()]

    return {
        "chart_id": "transactions_over_time",
        "title": "Transactions over time",
        "data": [
            {
                "type": "scatter",
                "mode": "lines+markers",
                "name": "Daily transactions",
                "x": dates,
                "y": counts,
                "hovertemplate": (
                    "%{x}<br>Transactions %{y:,}<extra></extra>"
                ),
            }
        ],
        "layout": {
            "xaxis": {"title": "Date"},
            "yaxis": {"title": "Transaction count"},
        },
    }


def _category_chart(
    df: pd.DataFrame,
    column: str,
    *,
    chart_id: str,
    title: str,
    chart_type: str = "bar",
    limit: int = 12,
) -> dict:
    if column not in df:
        counts = pd.Series(dtype=int)
    else:
        counts = (
            df[column]
            .astype("string")
            .fillna("Unknown")
            .replace("", "Unknown")
            .value_counts()
            .head(limit)
        )
    labels = [str(item) for item in counts.index]
    values = [int(item) for item in counts.to_numpy()]
    if chart_type == "pie":
        data = [{
            "type": "pie",
            "labels": labels,
            "values": values,
            "hole": 0.58,
            "textinfo": "label+percent",
            "hovertemplate": "%{label}<br>%{value:,}<extra></extra>",
        }] if values else []
    else:
        data = [{
            "type": "bar",
            "orientation": "h",
            "x": values[::-1],
            "y": labels[::-1],
            "hovertemplate": "%{y}<br>%{x:,}<extra></extra>",
        }] if values else []
    return {
        "chart_id": chart_id,
        "title": title,
        "data": data,
        "layout": {"margin": {"l": 100}} if chart_type == "bar" else {},
    }


def _customer_volume_chart(df: pd.DataFrame) -> dict:
    counts = (
        df["from_account"].value_counts()
        if "from_account" in df
        else pd.Series(dtype=int)
    )
    return {
        "chart_id": "customer_volume_distribution",
        "title": "Customer transaction-volume distribution",
        "data": [{
            "type": "box",
            "x": [int(value) for value in counts.to_numpy()],
            "name": "Transactions per customer",
            "boxpoints": "outliers",
            "hovertemplate": "%{x:,} transactions<extra></extra>",
        }] if len(counts) else [],
        "layout": {"xaxis": {"title": "Transactions per customer"}},
    }


def _percentile_chart(amounts: pd.Series) -> dict:
    quantiles = [0.5, 0.9, 0.95, 0.99]
    values = (
        [float(amounts.quantile(value)) for value in quantiles]
        if len(amounts)
        else []
    )
    return {
        "chart_id": "amount_percentiles",
        "title": "Transaction amount percentiles",
        "data": [{
            "type": "bar",
            "x": ["P50", "P90", "P95", "P99"],
            "y": values,
            "text": [f"{value:,.0f}" for value in values],
            "textposition": "auto",
            "hovertemplate": "%{x}<br>Amount %{y:,.2f}<extra></extra>",
        }] if values else [],
        "layout": {"yaxis": {"title": "Amount paid"}},
    }


def _risk_distribution_chart(df: pd.DataFrame) -> dict:
    if "risk_label" in df:
        values = df["risk_label"].astype("string").fillna("unknown")
    elif "is_laundering" in df:
        labels = pd.to_numeric(df["is_laundering"], errors="coerce").fillna(0)
        values = labels.map({0: "not labelled", 1: "known laundering"})
    else:
        values = pd.Series(dtype="string")
    counts = values.value_counts()
    return {
        "chart_id": "risk_label_distribution",
        "title": "Risk or label distribution",
        "data": [{
            "type": "bar",
            "x": [str(item) for item in counts.index],
            "y": [int(item) for item in counts.to_numpy()],
            "hovertemplate": "%{x}<br>%{y:,}<extra></extra>",
        }] if len(counts) else [],
        "layout": {"yaxis": {"title": "Transactions"}},
        "meta": {
            "note": (
                "Shows risk labels when available; otherwise source-dataset "
                "laundering labels. Empty for unlabelled pre-scoring slices."
            )
        },
    }


def _hour_heatmap(df: pd.DataFrame) -> dict:
    timestamps = (
        pd.to_datetime(df["timestamp"], errors="coerce").dropna()
        if "timestamp" in df
        else pd.Series(dtype="datetime64[ns]")
    )
    if timestamps.empty:
        matrix = np.zeros((7, 24), dtype=int)
    else:
        frame = pd.DataFrame({
            "weekday": timestamps.dt.dayofweek,
            "hour": timestamps.dt.hour,
        })
        matrix = (
            frame.groupby(["weekday", "hour"])
            .size()
            .unstack(fill_value=0)
            .reindex(index=range(7), columns=range(24), fill_value=0)
            .to_numpy(dtype=int)
        )
    return {
        "chart_id": "hour_of_day_heatmap",
        "title": "Transaction timing heatmap",
        "data": [{
            "type": "heatmap",
            "x": list(range(24)),
            "y": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "z": matrix.tolist(),
            "colorscale": "Viridis",
            "hovertemplate": "%{y} %{x}:00<br>%{z:,} transactions<extra></extra>",
        }] if len(df) else [],
        "layout": {"xaxis": {"title": "Hour of day"}},
    }


def _missing_data_chart(df: pd.DataFrame) -> dict:
    missing = df.isna().sum().sort_values(ascending=False)
    return {
        "chart_id": "missing_data_assessment",
        "title": "Missing data assessment",
        "data": [{
            "type": "bar",
            "x": [str(item) for item in missing.index],
            "y": [int(item) for item in missing.to_numpy()],
            "hovertemplate": "%{x}<br>%{y:,} missing<extra></extra>",
        }] if len(missing) else [],
        "layout": {
            "xaxis": {"title": "Field", "tickangle": -35},
            "yaxis": {"title": "Missing values"},
        },
    }


def run_eda(df: pd.DataFrame, filters: dict | None = None) -> dict:
    """Return reviewer-grade profiling over only the query-filtered slice."""
    amounts = _amount_series(df)
    timestamps = (
        pd.to_datetime(df["timestamp"], errors="coerce")
        if "timestamp" in df
        else pd.Series(dtype="datetime64[ns]")
    )

    summary: dict[str, Any] = {
        "row_count": int(len(df)),
        "amount_total": float(amounts.sum()) if not amounts.empty else 0.0,
        "amount_mean": float(amounts.mean()) if not amounts.empty else None,
        "amount_median": (
            float(amounts.median()) if not amounts.empty else None
        ),
        "amount_max": float(amounts.max()) if not amounts.empty else None,
        "amount_p90": float(amounts.quantile(0.90)) if not amounts.empty else None,
        "amount_p99": float(amounts.quantile(0.99)) if not amounts.empty else None,
        "unique_from_accounts": (
            int(df["from_account"].nunique())
            if "from_account" in df
            else 0
        ),
        "unique_to_accounts": (
            int(df["to_account"].nunique())
            if "to_account" in df
            else 0
        ),
        "date_min": (
            timestamps.min().isoformat()
            if not timestamps.empty and timestamps.notna().any()
            else None
        ),
        "date_max": (
            timestamps.max().isoformat()
            if not timestamps.empty and timestamps.notna().any()
            else None
        ),
        "filters": {
            key: _json_scalar(value)
            for key, value in (filters or {}).items()
        },
        "missing_values": {
            str(column): int(value)
            for column, value in df.isna().sum().items()
        },
    }

    if "is_laundering" in df:
        labels = pd.to_numeric(df["is_laundering"], errors="coerce").fillna(0)
        summary["labelled_laundering_count"] = int(labels.eq(1).sum())
        summary["labelled_laundering_rate_pct"] = (
            round(float(labels.mean() * 100), 4) if len(labels) else 0.0
        )

    if "payment_format" in df:
        summary["payment_formats"] = {
            str(key): int(value)
            for key, value in df["payment_format"]
            .astype("string")
            .fillna("Unknown")
            .value_counts()
            .head(10)
            .items()
        }

    charts = [
        _amount_histogram(amounts),
        _transactions_over_time(df),
        _category_chart(
            df,
            "payment_format",
            chart_id="payment_format_distribution",
            title="Payment format distribution",
            chart_type="pie",
        ),
        _category_chart(
            df,
            "from_country",
            chart_id="sender_country_breakdown",
            title="Sender country breakdown",
        ),
        _customer_volume_chart(df),
        _percentile_chart(amounts),
        _risk_distribution_chart(df),
        _category_chart(
            df,
            "laundering_type",
            chart_id="typology_frequency",
            title="Known typology frequency",
        ),
        _hour_heatmap(df),
        _missing_data_chart(df),
    ] if len(df) else []
    return {
        "summary_stats": summary,
        "charts": charts,
        "note": (
            "EDA reflects only the filtered rows supplied by data_loader; "
            "no values are extrapolated to the full dataset."
        ),
    }
