"""Query-selective AML feature families computed over an in-memory slice."""
from __future__ import annotations

from collections.abc import Iterable

import duckdb
import numpy as np
import pandas as pd


FEATURE_COLUMNS = [
    "txn_count_7d",
    "rolling_sum_7d",
    "near_threshold_count",
    "amount_deviation",
    "velocity_1hr",
    "fan_in_count",
    "cross_border_flag",
]

_EXTRA_RULE_COLUMNS = [
    "fan_in_sum_48h",
    "fan_out_count",
    "recent_inflow_24h",
]
_DERIVED_COLUMNS = FEATURE_COLUMNS + _EXTRA_RULE_COLUMNS

FEATURE_FAMILIES: dict[str, tuple[str, ...]] = {
    "structuring_features": (
        "txn_count_7d",
        "rolling_sum_7d",
        "near_threshold_count",
    ),
    "velocity_features": (
        "velocity_1hr",
        "fan_in_count",
        "fan_in_sum_48h",
    ),
    "rapid_cashout_features": (
        "recent_inflow_24h",
        "velocity_1hr",
        "txn_count_7d",
    ),
    "fan_in_out_features": (
        "fan_in_count",
        "fan_out_count",
        "fan_in_sum_48h",
    ),
    "behavioral_features": ("amount_deviation",),
    "graph_features": ("cross_border_flag",),
}

MODEL_FEATURE_FAMILIES = (
    "structuring_features",
    "velocity_features",
    "behavioral_features",
)

_PATTERN_FAMILIES: dict[str, tuple[str, ...]] = {
    "structuring": ("structuring_features",),
    "smurfing": ("structuring_features", "velocity_features"),
    "rapid_cashout": ("rapid_cashout_features",),
    "cash_withdrawal": ("rapid_cashout_features",),
    "deposit_send": ("rapid_cashout_features",),
    "fan_in": ("fan_in_out_features",),
    "fan_out": ("fan_in_out_features",),
    "layering": ("fan_in_out_features", "graph_features"),
    "round_trip": ("fan_in_out_features", "graph_features"),
    "cycle": ("fan_in_out_features", "graph_features"),
    "bipartite": ("fan_in_out_features", "graph_features"),
    "behavioural_change": ("behavioral_features",),
    "behavioral_change": ("behavioral_features",),
    "single_large": (),
}


def selected_feature_families(
    pattern_types: list[str] | None = None,
    *,
    require_model_features: bool = False,
) -> list[str]:
    """Resolve the smallest ordered family set for a query and detector plan."""
    if pattern_types is None:
        selected = set(FEATURE_FAMILIES)
    else:
        selected = {
            family
            for pattern in pattern_types
            for family in _PATTERN_FAMILIES.get(pattern, ("behavioral_features",))
        }
    if require_model_features:
        selected.update(MODEL_FEATURE_FAMILIES)
    return [family for family in FEATURE_FAMILIES if family in selected]


def _canonicalise_input(df: pd.DataFrame) -> pd.DataFrame:
    result = df.drop(
        columns=[column for column in _DERIVED_COLUMNS if column in df],
        errors="ignore",
    ).copy()
    if "amount_paid" not in result and "amount" in result:
        result["amount_paid"] = result["amount"]
    required = {"timestamp", "from_account", "to_account", "amount_paid"}
    missing = sorted(required.difference(result.columns))
    if missing:
        raise ValueError(
            "feature engineering requires columns: " + ", ".join(missing)
        )
    result["timestamp"] = pd.to_datetime(result["timestamp"], errors="coerce")
    result["amount_paid"] = pd.to_numeric(result["amount_paid"], errors="coerce")
    result["from_account"] = (
        result["from_account"].astype("string").fillna("").str.strip()
    )
    result["to_account"] = (
        result["to_account"].astype("string").fillna("").str.strip()
    )
    result.insert(0, "__row_id", np.arange(len(result), dtype=np.int64))
    return result


def _window_features(
    df: pd.DataFrame,
    requested: set[str],
) -> pd.DataFrame:
    expressions = ["__row_id"]
    windows: list[str] = []
    seven_day = requested.intersection(
        {"txn_count_7d", "rolling_sum_7d", "near_threshold_count"}
    )
    if "txn_count_7d" in seven_day:
        expressions.append("count(*) OVER seven_day AS txn_count_7d")
    if "rolling_sum_7d" in seven_day:
        expressions.append(
            "coalesce(sum(amount_paid) OVER seven_day, 0.0) AS rolling_sum_7d"
        )
    if "near_threshold_count" in seven_day:
        expressions.append(
            """
            coalesce(sum(CASE WHEN amount_paid >= 8000
                                   AND amount_paid < 10000
                              THEN 1 ELSE 0 END) OVER seven_day, 0)
                AS near_threshold_count
            """
        )
    if seven_day:
        windows.append(
            """
            seven_day AS (
                PARTITION BY from_account ORDER BY timestamp
                RANGE BETWEEN INTERVAL '7 days' PRECEDING AND CURRENT ROW
            )
            """
        )
    if "velocity_1hr" in requested:
        expressions.append("count(*) OVER one_hour AS velocity_1hr")
        windows.append(
            """
            one_hour AS (
                PARTITION BY from_account ORDER BY timestamp
                RANGE BETWEEN INTERVAL '1 hour' PRECEDING AND CURRENT ROW
            )
            """
        )
    if "fan_in_sum_48h" in requested:
        expressions.append(
            "coalesce(sum(amount_paid) OVER fan_in_window, 0.0) AS fan_in_sum_48h"
        )
        windows.append(
            """
            fan_in_window AS (
                PARTITION BY to_account ORDER BY timestamp
                RANGE BETWEEN INTERVAL '48 hours' PRECEDING AND CURRENT ROW
            )
            """
        )
    if len(expressions) == 1:
        return df[["__row_id"]].copy()
    window_sql = "WINDOW " + ", ".join(windows) if windows else ""
    conn = duckdb.connect(":memory:")
    conn.register("_feature_source", df)
    try:
        return conn.execute(
            f"""
            SELECT {", ".join(expressions)}
            FROM _feature_source
            {window_sql}
            ORDER BY __row_id
            """
        ).df()
    finally:
        conn.unregister("_feature_source")
        conn.close()


def _range_join_feature(
    df: pd.DataFrame,
    feature: str,
) -> pd.Series:
    definitions = {
        "fan_in_count": (
            "count(DISTINCT history.from_account)",
            "history.to_account = current.to_account",
            "48 hours",
        ),
        "fan_out_count": (
            "count(DISTINCT history.to_account)",
            "history.from_account = current.from_account",
            "48 hours",
        ),
        "recent_inflow_24h": (
            "coalesce(sum(history.amount_paid), 0.0)",
            "history.to_account = current.from_account",
            "24 hours",
        ),
    }
    aggregate, join_key, interval = definitions[feature]
    conn = duckdb.connect(":memory:")
    conn.register("_feature_source", df)
    try:
        values = conn.execute(
            f"""
            SELECT current.__row_id, {aggregate} AS value
            FROM _feature_source AS current
            LEFT JOIN _feature_source AS history
              ON {join_key}
             AND history.timestamp BETWEEN
                    current.timestamp - INTERVAL '{interval}'
                    AND current.timestamp
            GROUP BY current.__row_id
            ORDER BY current.__row_id
            """
        ).df()
        return values.set_index("__row_id")["value"]
    finally:
        conn.unregister("_feature_source")
        conn.close()


def _amount_deviation(df: pd.DataFrame) -> np.ndarray:
    output = np.zeros(len(df), dtype=float)
    ordered = df[
        ["from_account", "timestamp", "amount_paid", "__row_id"]
    ].sort_values(
        ["from_account", "timestamp", "__row_id"],
        kind="stable",
        na_position="last",
    )
    amounts = ordered["amount_paid"].fillna(0.0)
    grouped = amounts.groupby(ordered["from_account"], sort=False)
    prior_mean = (grouped.cumsum() - amounts).div(
        grouped.cumcount().replace(0, np.nan)
    )
    deviation = (amounts - prior_mean).abs().div(prior_mean.abs())
    output[ordered["__row_id"].to_numpy(dtype=int)] = (
        deviation.replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy()
    )
    return output


def _add_cross_border(df: pd.DataFrame) -> None:
    if {"from_country", "to_country"}.issubset(df.columns):
        source = df["from_country"].astype("string").fillna("").str.strip()
        target = df["to_country"].astype("string").fillna("").str.strip()
        df["cross_border_flag"] = (
            source.ne("")
            & target.ne("")
            & source.str.casefold().ne(target.str.casefold())
        ).astype("int8")
    else:
        df["cross_border_flag"] = 0


def compute_feature_families(
    df: pd.DataFrame,
    families: Iterable[str],
) -> pd.DataFrame:
    """Compute only the explicitly selected families, preserving row order."""
    selected = list(dict.fromkeys(families))
    unknown = sorted(set(selected).difference(FEATURE_FAMILIES))
    if unknown:
        raise ValueError("unknown feature families: " + ", ".join(unknown))
    requested = {
        feature
        for family in selected
        for feature in FEATURE_FAMILIES[family]
    }
    working = _canonicalise_input(df)
    if working.empty:
        result = working.drop(columns="__row_id")
        for column in requested:
            result[column] = pd.Series(
                dtype="int64" if column in {
                    "txn_count_7d", "near_threshold_count", "velocity_1hr",
                    "fan_in_count", "fan_out_count", "cross_border_flag",
                } else "float64"
            )
        return result

    windows = _window_features(working, requested).set_index("__row_id")
    for column in requested.intersection(windows.columns):
        working[column] = working["__row_id"].map(windows[column])
    for column in requested.intersection(
        {"fan_in_count", "fan_out_count", "recent_inflow_24h"}
    ):
        working[column] = working["__row_id"].map(
            _range_join_feature(working, column)
        )
    if "amount_deviation" in requested:
        working["amount_deviation"] = _amount_deviation(working)
    if "cross_border_flag" in requested:
        _add_cross_border(working)

    integer_columns = requested.intersection(
        {
            "txn_count_7d", "near_threshold_count", "velocity_1hr",
            "fan_in_count", "fan_out_count", "cross_border_flag",
        }
    )
    for column in integer_columns:
        working[column] = (
            pd.to_numeric(working[column], errors="coerce")
            .fillna(0)
            .astype("int64")
        )
    for column in requested.difference(integer_columns):
        working[column] = (
            pd.to_numeric(working[column], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
            .astype(float)
        )
    return (
        working.sort_values("__row_id", kind="stable")
        .drop(columns="__row_id")
        .reset_index(drop=True)
    )


def compute_feature_family(df: pd.DataFrame, family: str) -> pd.DataFrame:
    """Public single-family entry point for tool-registry integrations."""
    return compute_feature_families(df, [family])


def engineer_features(
    df: pd.DataFrame,
    pattern_types: list[str] | None = None,
    *,
    require_model_features: bool = False,
) -> pd.DataFrame:
    """Compute the minimal family union needed by the query and detector plan."""
    families = selected_feature_families(
        pattern_types,
        require_model_features=require_model_features,
    )
    return compute_feature_families(df, families)
