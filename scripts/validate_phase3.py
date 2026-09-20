"""Run real-data Phase 3 validation without modifying model thresholds."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.data_loader import load
from tools.feature_engineering import engineer_features
from tools.ml_engine import get_model_bundle, run_ml
from tools.rule_engine import run_rules, validate_rules_against_saml
from tools.statistical import get_saml_iqr_bounds, run_statistical


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit",
        type=int,
        default=10_000,
        help="Number of HI-Small rows to spot-check",
    )
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be greater than zero")

    print("SAML-D rule recall:")
    print(json.dumps(validate_rules_against_saml(), indent=2))

    lower, upper = get_saml_iqr_bounds()
    print(f"\nSAML-D normal IQR bounds: {lower:.2f} .. {upper:.2f}")

    baseline_model = get_model_bundle()
    print(
        "Isolation Forest baseline rows: "
        f"{baseline_model.training_rows:,}"
    )

    primary = load(limit=args.limit)
    featured = engineer_features(primary)
    ruled = run_rules(featured)
    statistical = run_statistical(ruled)
    scored = run_ml(statistical, model_bundle=baseline_model)
    summary = {
        "hi_small_rows_checked": len(scored),
        "rows_with_rule_flags": int(scored["rule_flags"].map(bool).sum()),
        "rows_with_iqr_flag": int(scored["iqr_flag"].sum()),
        "isolation_forest_anomalies": int(scored["anomaly_label"].sum()),
        "ml_score_min": round(float(scored["ml_score"].min()), 6),
        "ml_score_max": round(float(scored["ml_score"].max()), 6),
    }
    print("\nHI-Small spot-check:")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
