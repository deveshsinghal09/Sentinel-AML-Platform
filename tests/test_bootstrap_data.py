from __future__ import annotations

import hashlib

import duckdb
import pytest

from scripts.bootstrap_data import download_database, verify_database


def _valid_database(path):
    conn = duckdb.connect(str(path))
    conn.execute("CREATE TABLE transactions (id INTEGER)")
    conn.execute("CREATE TABLE saml_knowledge (id INTEGER)")
    conn.close()


def test_verify_database_requires_both_governed_tables(tmp_path):
    incomplete = tmp_path / "incomplete.duckdb"
    conn = duckdb.connect(str(incomplete))
    conn.execute("CREATE TABLE transactions (id INTEGER)")
    conn.close()
    with pytest.raises(RuntimeError, match="saml_knowledge"):
        verify_database(incomplete)


def test_download_database_checks_hash_and_installs_atomically(tmp_path):
    source = tmp_path / "source.duckdb"
    destination = tmp_path / "installed.duckdb"
    _valid_database(source)
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()

    download_database(source.as_uri(), checksum, destination)

    assert destination.exists()
    verify_database(destination)
    assert not destination.with_suffix(".duckdb.download").exists()
