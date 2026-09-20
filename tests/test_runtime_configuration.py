from __future__ import annotations

from pathlib import Path

import pytest

from config import ConfigurationError, PROJECT_ROOT, Settings


def test_settings_reject_inverted_risk_thresholds(monkeypatch):
    monkeypatch.setenv("RISK_LOW_THRESHOLD", "0.90")
    monkeypatch.setenv("RISK_HIGH_THRESHOLD", "0.70")

    with pytest.raises(ConfigurationError, match="must be lower"):
        Settings.from_environment()


def test_settings_reject_wildcard_credential_origin(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")

    with pytest.raises(ConfigurationError, match="cannot use"):
        Settings.from_environment()


def test_settings_resolve_governed_paths_from_project_root(monkeypatch):
    monkeypatch.setenv("DB_PATH", "runtime/test.duckdb")
    settings = Settings.from_environment()

    assert settings.db_path == (PROJECT_ROOT / "runtime/test.duckdb").resolve()
    assert isinstance(settings.db_path, Path)


def test_llm_configuration_reports_presence_without_exposing_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-never-logged")

    settings = Settings.from_environment()

    assert settings.llm_configured is True
    assert "test-key-never-logged" not in repr(settings.llm_configured)
