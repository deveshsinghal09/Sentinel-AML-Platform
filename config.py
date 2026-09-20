"""Validated runtime configuration for Sentinel AML.

Application modules import the compatibility constants at the bottom of this
module. Environment access and validation stay centralized here so secrets are
never read or logged ad hoc by business logic.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env", override=False)


class ConfigurationError(ValueError):
    """Raised when runtime settings are internally inconsistent."""


def _text(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip()
    if not value:
        raise ConfigurationError(f"{name} cannot be empty")
    return value


def _integer(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{name} must be at most {maximum}")
    return value


def _number(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be numeric") from exc
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{name} must be at most {maximum}")
    return value


def _path(name: str, default: str) -> Path:
    configured = Path(os.environ.get(name, default).strip()).expanduser()
    return (
        configured.resolve()
        if configured.is_absolute()
        else (PROJECT_ROOT / configured).resolve()
    )


def _origins() -> tuple[str, ...]:
    origins = tuple(
        origin.strip().rstrip("/")
        for origin in os.environ.get(
            "ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    )
    if not origins:
        raise ConfigurationError("ALLOWED_ORIGINS must contain at least one origin")
    if "*" in origins:
        raise ConfigurationError(
            "ALLOWED_ORIGINS cannot use '*' because the API allows credentials"
        )
    return origins


@dataclass(frozen=True, slots=True)
class Settings:
    app_environment: str
    groq_api_key: str
    intent_model: str
    explanation_model: str
    fallback_model: str
    data_dir: Path
    db_path: Path
    csv_path: Path
    accounts_csv_path: Path
    saml_d_path: Path
    upload_dir: Path
    max_upload_bytes: int
    max_query_rows: int
    api_host: str
    api_port: int
    log_level: str
    allowed_origins: tuple[str, ...]
    risk_low_threshold: float
    risk_high_threshold: float
    ctr_threshold: float
    structuring_window_days: int
    structuring_min_txns: int

    @property
    def llm_configured(self) -> bool:
        """Return whether an LLM key is present without exposing its value."""
        return bool(self.groq_api_key)

    @classmethod
    def from_environment(cls) -> "Settings":
        low_threshold = _number(
            "RISK_LOW_THRESHOLD",
            0.35,
            minimum=0,
            maximum=1,
        )
        high_threshold = _number(
            "RISK_HIGH_THRESHOLD",
            0.70,
            minimum=0,
            maximum=1,
        )
        if low_threshold >= high_threshold:
            raise ConfigurationError(
                "RISK_LOW_THRESHOLD must be lower than RISK_HIGH_THRESHOLD"
            )

        log_level = _text("LOG_LEVEL", "info").lower()
        if log_level not in {"debug", "info", "warning", "error", "critical"}:
            raise ConfigurationError(
                "LOG_LEVEL must be debug, info, warning, error, or critical"
            )

        return cls(
            app_environment=_text("APP_ENV", "development").lower(),
            groq_api_key=os.environ.get("GROQ_API_KEY", "").strip(),
            intent_model=_text("INTENT_MODEL", "openai/gpt-oss-20b"),
            explanation_model=_text(
                "EXPLANATION_MODEL",
                "openai/gpt-oss-120b",
            ),
            fallback_model=_text("FALLBACK_MODEL", "qwen/qwen3-27b"),
            data_dir=_path("DATA_DIR", "dataset"),
            db_path=_path("DB_PATH", "dataset/aml.duckdb"),
            csv_path=_path("CSV_PATH", "dataset/HI-Small_Trans.csv"),
            accounts_csv_path=_path(
                "ACCOUNTS_CSV_PATH",
                "dataset/HI-Small_accounts.csv",
            ),
            saml_d_path=_path("SAML_D_PATH", "dataset/SAML-D.csv"),
            upload_dir=_path("UPLOAD_DIR", "dataset/uploads"),
            max_upload_bytes=_integer(
                "MAX_UPLOAD_BYTES",
                5 * 1024 * 1024 * 1024,
                minimum=1,
            ),
            max_query_rows=_integer(
                "MAX_QUERY_ROWS",
                100_000,
                minimum=1,
                maximum=1_000_000,
            ),
            api_host=_text("API_HOST", "0.0.0.0"),
            api_port=_integer("API_PORT", 8000, minimum=1, maximum=65_535),
            log_level=log_level,
            allowed_origins=_origins(),
            risk_low_threshold=low_threshold,
            risk_high_threshold=high_threshold,
            ctr_threshold=_number("CTR_THRESHOLD", 10_000, minimum=1),
            structuring_window_days=_integer(
                "STRUCTURING_WINDOW_DAYS",
                3,
                minimum=1,
                maximum=90,
            ),
            structuring_min_txns=_integer(
                "STRUCTURING_MIN_TXNS",
                3,
                minimum=2,
                maximum=10_000,
            ),
        )


settings = Settings.from_environment()

# Compatibility constants used by existing agent, API, and tool modules.
APP_ENV = settings.app_environment
GROQ_API_KEY = settings.groq_api_key
INTENT_MODEL = settings.intent_model
EXPLANATION_MODEL = settings.explanation_model
FALLBACK_MODEL = settings.fallback_model
DATA_DIR = settings.data_dir
DB_PATH = settings.db_path
CSV_PATH = settings.csv_path
ACCOUNTS_CSV_PATH = settings.accounts_csv_path
SAML_D_PATH = settings.saml_d_path
UPLOAD_DIR = settings.upload_dir
MAX_UPLOAD_BYTES = settings.max_upload_bytes
MAX_QUERY_ROWS = settings.max_query_rows
API_HOST = settings.api_host
API_PORT = settings.api_port
LOG_LEVEL = settings.log_level
ALLOWED_ORIGINS = list(settings.allowed_origins)
RISK_LOW_THRESHOLD = settings.risk_low_threshold
RISK_HIGH_THRESHOLD = settings.risk_high_threshold
CTR_THRESHOLD = settings.ctr_threshold
STRUCTURING_WINDOW_DAYS = settings.structuring_window_days
STRUCTURING_MIN_TXNS = settings.structuring_min_txns
