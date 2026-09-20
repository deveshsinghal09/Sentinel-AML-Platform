"""Small allowlisted JSON events; never serialize customer records or exceptions."""
import json
import logging

_FIELDS = {"investigation_id", "dataset_id", "risk_score", "request_id",
           "duration_ms", "status", "error_type", "error_code", "method", "status_code"}


def event(name: str, **fields) -> None:
    logging.getLogger("sentinel.aws").info(json.dumps(
        {"event": name, **{k: v for k, v in fields.items() if k in _FIELDS}},
        default=str,
    ))


def configure() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)
