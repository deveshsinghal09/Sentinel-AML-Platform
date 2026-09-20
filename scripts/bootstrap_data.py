"""Securely bootstrap a prebuilt DuckDB database onto a persistent volume."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.request import Request, urlopen

import duckdb

from config import DB_PATH


CHUNK_SIZE = 8 * 1024 * 1024
MAX_DATABASE_BYTES = 5 * 1024 * 1024 * 1024


def verify_database(path: Path) -> None:
    """Reject bundles that do not contain both governed analytical tables."""
    conn = duckdb.connect(str(path), read_only=True)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                """
            ).fetchall()
        }
    finally:
        conn.close()
    required = {"transactions", "saml_knowledge"}
    missing = required.difference(tables)
    if missing:
        raise RuntimeError(
            "Database bundle is missing required tables: "
            + ", ".join(sorted(missing))
        )


def download_database(url: str, expected_sha256: str, destination: Path) -> None:
    """Download, size-bound, checksum, verify, and atomically install a DB."""
    expected = expected_sha256.strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ValueError("DATA_BUNDLE_SHA256 must be a 64-character SHA-256")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".download")
    digest = hashlib.sha256()
    downloaded = 0
    request = Request(url, headers={"User-Agent": "Sentinel-AML/1.0"})
    try:
        with urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            while chunk := response.read(CHUNK_SIZE):
                downloaded += len(chunk)
                if downloaded > MAX_DATABASE_BYTES:
                    raise RuntimeError("Database bundle exceeds the 5 GiB safety limit")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError("Database bundle checksum mismatch")
        verify_database(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    if DB_PATH.exists():
        verify_database(DB_PATH)
        return
    url = os.environ.get("DATA_BUNDLE_URL", "").strip()
    checksum = os.environ.get("DATA_BUNDLE_SHA256", "").strip()
    if not url or not checksum:
        raise SystemExit(
            "DATA_BUNDLE_URL and DATA_BUNDLE_SHA256 are required when "
            "the persistent database is absent"
        )
    download_database(url, checksum, DB_PATH)


if __name__ == "__main__":
    main()
