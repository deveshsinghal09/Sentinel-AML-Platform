"""Statistical anomaly scoring calibrated on SAML-D normal behaviour."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
from loguru import logger


Z_SCORE_THRESHOLD = 3.0
IQR_MULTIPLIER = 1.5


@lru_cache(maxsize=1)
def get_saml_iqr_bounds() -> tuple[float, float]:
    """Load and cache amount bounds from sampled SAML-D normal rows."""
    from tools.data_loader import get_db_connection

    conn = get_db_connection()
    try:
        q1, q3 = conn.execute(
            """
            SELECT
                quantile_cont(amount, 0.25),
                quantile_cont(amount, 0.75)
            FROM saml_knowledge
            WHERE is_laundering = 0
              AND amount IS NOT NULL
            """
        ).fetchone()
    finally:
        conn.close()

    if q1 is None or q3 is None:
        raise RuntimeError("SAML-D normal baseline has no usable amounts")
    iqr = float(q3) - float(q1)
    lower = float(q1) - IQR_MULTIPLIER * iqr
    upper = float(q3) + IQR_MULTIPLIER * iqr
    logger.info(
        "SAML-D normal IQR baseline loaded: lower={:.2f}, upper={:.2f}",
        lower,
        upper,
    )
    return lower, upper


def run_statistical(
    df: pd.DataFrame,
    iqr_bounds: tuple[float, float] | None = None,
) -> pd.DataFrame:
    """Add per-account z-score, SAML-D IQR flag, and ``stat_score``."""
    result = df.copy()
    if "amount_paid" not in result and "amount" in result:
        result["amount_paid"] = result["amount"]
    required = {"from_account", "amount_paid"}
    missing = sorted(required.difference(result.columns))
    if missing:
        raise ValueError(
            "statistical scoring requires columns: " + ", ".join(missing)
        )

    amount = pd.to_numeric(result["amount_paid"], errors="coerce")
    accounts = result["from_account"].astype("string").fillna("")
    means = amount.groupby(accounts, sort=False).transform("mean")
    stds = amount.groupby(accounts, sort=False).transform(
        lambda values: values.std(ddof=0)
    )
    z_score = (amount - means).div(stds.replace(0, np.nan))
    z_score = z_score.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    lower, upper = iqr_bounds or get_saml_iqr_bounds()
    iqr_flag = amount.lt(lower) | amount.gt(upper)
    z_component = (z_score.abs() / Z_SCORE_THRESHOLD).clip(0.0, 1.0)

    result["z_score"] = z_score.astype(float)
    result["iqr_flag"] = iqr_flag.fillna(False).astype(bool)
    result["stat_score"] = np.maximum(
        z_component.fillna(0.0).to_numpy(dtype=float),
        result["iqr_flag"].to_numpy(dtype=float),
    )
    return result
