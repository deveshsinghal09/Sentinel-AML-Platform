"""Secure schema detection and canonical normalization for analyst uploads."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pandas as pd

from tools.data_loader import _TRANSACTION_COLUMNS


MIN_ANALYTICAL_ROWS = 100
SUPPORTED_EXTENSIONS = {".csv", ".xlsx"}

ALIASES: dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "date", "txn_date", "transaction_date", "time"),
    "from_bank": ("from_bank", "sender_bank", "ordering_institution"),
    "from_account": (
        "from_account", "sender_id", "sender_account", "account",
        "account_from", "ordering_customer",
    ),
    "to_bank": ("to_bank", "receiver_bank", "beneficiary_institution"),
    "to_account": (
        "to_account", "receiver_id", "receiver_account", "account.1",
        "account_to", "beneficiary_customer",
    ),
    "amount_paid": ("amount_paid", "amount", "payment_amount", "value"),
    "amount_received": ("amount_received", "received_amount"),
    "paying_currency": (
        "paying_currency", "payment_currency", "currency", "currency_code",
    ),
    "receiving_currency": ("receiving_currency", "received_currency"),
    "payment_format": (
        "payment_format", "payment_type", "transaction_type", "channel",
    ),
    "is_laundering": (
        "is_laundering", "laundering_flag", "suspicious_label",
    ),
}


@dataclass(frozen=True)
class SchemaInspection:
    schema_name: str
    column_map: dict[str, str]
    columns: list[str]
    preview: list[dict[str, object]]
    warnings: list[str]


def _normalized_columns(columns: list[str]) -> dict[str, str]:
    return {str(column).strip().lower(): str(column) for column in columns}


def detect_schema(frame: pd.DataFrame) -> tuple[str, dict[str, str]]:
    """Detect IBM AML, SAML-D, or a generic canonical transaction mapping."""
    available = _normalized_columns(list(frame.columns))
    if {
        "timestamp", "from bank", "account", "to bank", "account.1",
        "amount paid", "payment format",
    }.issubset(available):
        return "ibm_aml", {
            "timestamp": available["timestamp"],
            "from_bank": available["from bank"],
            "from_account": available["account"],
            "to_bank": available["to bank"],
            "to_account": available["account.1"],
            "amount_paid": available["amount paid"],
            "amount_received": available.get("amount received", available["amount paid"]),
            "paying_currency": available.get(
                "paying currency",
                available.get("payment currency", ""),
            ),
            "receiving_currency": available.get("receiving currency", ""),
            "payment_format": available["payment format"],
            "is_laundering": available.get("is laundering", ""),
        }
    if {
        "sender_account", "receiver_account", "amount",
        "is_laundering", "laundering_type",
    }.issubset(available):
        return "saml_d", {
            "from_account": available["sender_account"],
            "to_account": available["receiver_account"],
            "amount_paid": available["amount"],
            "is_laundering": available["is_laundering"],
        }

    mapping: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        for alias in aliases:
            if alias in available:
                mapping[canonical] = available[alias]
                break
    required = {"timestamp", "from_account", "to_account", "amount_paid"}
    return (
        "generic_transactions" if required.issubset(mapping) else "unmapped",
        mapping,
    )


def read_preview(path: Path, rows: int = 5) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
            low_memory=False,
            nrows=rows,
        )
    if suffix == ".xlsx":
        return pd.read_excel(path, dtype=str, keep_default_na=False, nrows=rows)
    raise ValueError("Only CSV and Excel (.xlsx) uploads are supported")


def inspect_upload(path: Path) -> SchemaInspection:
    frame = read_preview(path)
    schema_name, column_map = detect_schema(frame)
    warnings: list[str] = []
    if schema_name == "unmapped":
        missing = sorted(
            {"timestamp", "from_account", "to_account", "amount_paid"}
            .difference(column_map)
        )
        warnings.append("Manual mapping required for: " + ", ".join(missing))
    if "is_laundering" not in column_map:
        warnings.append("No ground-truth laundering label; labels default to 0")
    return SchemaInspection(
        schema_name=schema_name,
        column_map=column_map,
        columns=[str(column) for column in frame.columns],
        preview=frame.head(5).to_dict(orient="records"),
        warnings=warnings,
    )


def _series(
    raw: pd.DataFrame,
    mapping: dict[str, str],
    canonical: str,
    default: object = "",
) -> pd.Series:
    source = mapping.get(canonical)
    if source and source in raw:
        return raw[source]
    return pd.Series(default, index=raw.index)


def normalize_primary_frame(
    raw: pd.DataFrame,
    mapping: dict[str, str],
) -> pd.DataFrame:
    """Normalize and strictly validate a primary transaction frame."""
    required = {"timestamp", "from_account", "to_account", "amount_paid"}
    missing = sorted(required.difference(mapping))
    if missing:
        raise ValueError("Missing required mappings: " + ", ".join(missing))

    paid = pd.to_numeric(_series(raw, mapping, "amount_paid"), errors="coerce")
    received = pd.to_numeric(
        _series(raw, mapping, "amount_received", None),
        errors="coerce",
    ).fillna(paid)
    timestamps = pd.to_datetime(
        _series(raw, mapping, "timestamp"),
        errors="coerce",
    )
    from_accounts = _series(raw, mapping, "from_account").astype("string").str.strip()
    to_accounts = _series(raw, mapping, "to_account").astype("string").str.strip()
    invalid = (
        timestamps.isna()
        | paid.isna()
        | paid.le(0)
        | from_accounts.eq("")
        | to_accounts.eq("")
    )
    if invalid.any():
        raise ValueError(
            f"{int(invalid.sum()):,} rows fail required timestamp, account, "
            "or positive-amount validation"
        )

    paying_currency = (
        _series(raw, mapping, "paying_currency", "USD")
        .astype("string").fillna("USD").str.strip().replace("", "USD")
    )
    receiving_currency = (
        _series(raw, mapping, "receiving_currency", "")
        .astype("string").fillna("").str.strip()
    )
    receiving_currency = receiving_currency.mask(
        receiving_currency.eq(""),
        paying_currency,
    )
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "from_bank": _series(raw, mapping, "from_bank").astype("string").fillna("").str.strip(),
            "from_account": from_accounts,
            "to_bank": _series(raw, mapping, "to_bank").astype("string").fillna("").str.strip(),
            "to_account": to_accounts,
            "amount_received": received.astype(float),
            "receiving_currency": receiving_currency,
            "amount_paid": paid.astype(float),
            "paying_currency": paying_currency,
            "payment_format": (
                _series(raw, mapping, "payment_format", "Unknown")
                .astype("string").fillna("Unknown").str.strip().replace("", "Unknown")
            ),
            "is_laundering": (
                pd.to_numeric(
                    _series(raw, mapping, "is_laundering", 0),
                    errors="coerce",
                ).fillna(0).clip(0, 1).astype("int8")
            ),
        }
    )
    frame["txn_date"] = frame["timestamp"].dt.date
    frame["amount_usd"] = frame["amount_paid"]
    return frame[_TRANSACTION_COLUMNS]


def iter_primary_frames(
    path: Path,
    mapping: dict[str, str],
    chunksize: int = 100_000,
) -> Iterator[pd.DataFrame]:
    if path.suffix.lower() == ".csv":
        for raw in pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
            low_memory=False,
            chunksize=chunksize,
        ):
            yield normalize_primary_frame(raw, mapping)
        return
    raw = pd.read_excel(path, dtype=str, keep_default_na=False)
    yield normalize_primary_frame(raw, mapping)
