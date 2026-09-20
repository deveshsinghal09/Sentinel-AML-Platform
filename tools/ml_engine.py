"""Isolation Forest scoring trained on the SAML-D normal sample."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.ensemble import IsolationForest


FEATURES = [
    "txn_count_7d",
    "rolling_sum_7d",
    "near_threshold_count",
    "amount_deviation",
    "velocity_1hr",
    "fan_in_count",
]

CONTAMINATION = 0.001
RANDOM_STATE = 42


@dataclass(frozen=True)
class IsolationForestBundle:
    """Fitted estimator plus training-score bounds for normalization."""

    model: Any
    raw_min: float
    raw_max: float
    training_rows: int
    reference_features: dict[str, np.ndarray]


_MODEL_BUNDLES: dict[str, IsolationForestBundle] = {}
_MODEL_LOCK = Lock()


def _ensure_features(df: pd.DataFrame) -> pd.DataFrame:
    if set(FEATURES).issubset(df.columns):
        return df.copy()
    from tools.feature_engineering import engineer_features

    return engineer_features(df)


def _feature_matrix(df: pd.DataFrame) -> np.ndarray:
    values = df.reindex(columns=FEATURES).apply(
        pd.to_numeric,
        errors="coerce",
    )
    return (
        values.replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
        .to_numpy(dtype=float)
    )


def train_isolation_forest(
    baseline_df: pd.DataFrame,
    contamination: float = CONTAMINATION,
    random_state: int = RANDOM_STATE,
    n_estimators: int = 200,
) -> IsolationForestBundle:
    """Fit an Isolation Forest on a normal-behaviour feature baseline."""
    if not 0 < contamination <= 0.5:
        raise ValueError("contamination must be in (0, 0.5]")
    featured = _ensure_features(baseline_df)
    matrix = _feature_matrix(featured)
    if len(matrix) < 2:
        raise ValueError("at least two baseline rows are required")

    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(matrix)
    raw_training = -model.decision_function(matrix)
    return IsolationForestBundle(
        model=model,
        raw_min=float(np.min(raw_training)),
        raw_max=float(np.max(raw_training)),
        training_rows=len(matrix),
        reference_features={
            feature: matrix[:, index].copy()
            for index, feature in enumerate(FEATURES)
        },
    )


def _active_knowledge_context() -> tuple[str, str]:
    from tools.data_loader import get_db_connection
    from tools.dataset_store import resolve_knowledge_table

    conn = get_db_connection()
    try:
        return resolve_knowledge_table(conn)
    finally:
        conn.close()


def _load_saml_normal_baseline(table_name: str) -> pd.DataFrame:
    from tools.data_loader import get_db_connection

    conn = get_db_connection()
    try:
        return conn.execute(
            f"""
            SELECT
                timestamp,
                from_account,
                to_account,
                amount AS amount_paid,
                payment_format,
                from_country,
                to_country
            FROM {table_name}
            WHERE is_laundering = 0
            ORDER BY timestamp
            """
        ).df()
    finally:
        conn.close()


def get_model_bundle(dataset_id: str | None = None) -> IsolationForestBundle:
    """Lazily train and cache the SAML-D normal-baseline model."""
    table_name, knowledge_id = _active_knowledge_context()
    key = dataset_id or f"active:{knowledge_id}"
    if key not in _MODEL_BUNDLES:
        with _MODEL_LOCK:
            if key not in _MODEL_BUNDLES:
                baseline = _load_saml_normal_baseline(table_name)
                logger.info(
                    "Training Isolation Forest on {:,} SAML-D normal rows",
                    len(baseline),
                )
                _MODEL_BUNDLES[key] = train_isolation_forest(baseline)
                logger.success(
                    "Isolation Forest ready: {:,} baseline rows",
                    _MODEL_BUNDLES[key].training_rows,
                )
    return _MODEL_BUNDLES[key]


def clear_model_cache() -> None:
    """Clear the process-local model cache (primarily for tests/re-ingest)."""
    with _MODEL_LOCK:
        _MODEL_BUNDLES.clear()


def run_ml(
    df: pd.DataFrame,
    model_bundle: IsolationForestBundle | None = None,
    dataset_id: str | None = None,
) -> pd.DataFrame:
    """Add normalized Isolation Forest scores and anomaly labels."""
    result = _ensure_features(df)
    if result.empty:
        result["iso_score"] = pd.Series(dtype=float)
        result["anomaly_label"] = pd.Series(dtype="int8")
        result["ml_score"] = pd.Series(dtype=float)
        return result

    bundle = model_bundle or get_model_bundle(dataset_id)
    matrix = _feature_matrix(result)
    raw = -bundle.model.decision_function(matrix)
    span = bundle.raw_max - bundle.raw_min
    if span <= np.finfo(float).eps:
        normalized = np.zeros(len(raw), dtype=float)
    else:
        normalized = np.clip(
            (raw - bundle.raw_min) / span,
            0.0,
            1.0,
        )
    labels = (bundle.model.predict(matrix) == -1).astype("int8")

    result["iso_score"] = normalized
    result["anomaly_label"] = labels
    result["ml_score"] = normalized
    return result
