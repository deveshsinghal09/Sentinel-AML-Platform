from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import datasets


DATASETS = [
    {
        "dataset_id": "ibm-hi-small-v1",
        "display_name": "HI-Small Transactions",
        "source_file": r"C:\restricted\evidence\HI-Small_Trans.csv",
        "dataset_type": "primary",
        "file_size_bytes": 1_024,
        "row_count": 10_000,
        "laundering_count": 20,
        "laundering_rate": 0.002,
        "date_min": "2022-09-01",
        "date_max": "2022-09-30",
        "schema_version": "1.0",
        "md5_fingerprint": "a" * 32,
        "ingested_at": "2026-07-26T09:00:00Z",
        "is_active": True,
        "notes": "Governed primary evidence",
        "column_map": {},
        "schema_detected": "ibm_aml",
    },
    {
        "dataset_id": "saml-d-knowledge-v1",
        "display_name": "SAML-D Knowledge",
        "source_file": "/srv/restricted/SAML-D.csv",
        "dataset_type": "knowledge",
        "file_size_bytes": 512,
        "row_count": 4_000,
        "laundering_count": 400,
        "laundering_rate": 0.1,
        "date_min": None,
        "date_max": None,
        "schema_version": "1.0",
        "md5_fingerprint": "b" * 32,
        "ingested_at": "2026-07-26T09:01:00Z",
        "is_active": True,
        "notes": "Typology grounding",
        "column_map": {},
        "schema_detected": "saml_d",
    },
    {
        "dataset_id": "kyc-customer-v1",
        "display_name": "Customer KYC",
        "source_file": "customers.csv",
        "dataset_type": "kyc",
        "file_size_bytes": 256,
        "row_count": 250,
        "laundering_count": 0,
        "laundering_rate": 0,
        "date_min": None,
        "date_max": None,
        "schema_version": "1.0",
        "md5_fingerprint": "c" * 32,
        "ingested_at": "2026-07-26T09:02:00Z",
        "is_active": False,
        "notes": "Customer enrichment",
        "column_map": {},
        "schema_detected": "kyc",
    },
]


class FakeDatasetRepository:
    def __init__(self, records=None):
        self.records = deepcopy(DATASETS if records is None else records)

    def list_datasets(self):
        return self.records

    def get_dataset(self, dataset_id):
        return next(
            (
                record
                for record in self.records
                if record["dataset_id"] == dataset_id
            ),
            None,
        )


def _client(repository=None):
    app = FastAPI()
    app.include_router(datasets.router)
    app.dependency_overrides[datasets.get_dataset_repository] = (
        lambda: repository or FakeDatasetRepository()
    )
    return TestClient(app)


def test_list_filters_paginates_and_never_exposes_source_paths():
    with _client() as client:
        response = client.get(
            "/datasets",
            params={
                "active_only": "true",
                "limit": 1,
                "offset": 1,
            },
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert [item["dataset_id"] for item in response.json()] == [
        "saml-d-knowledge-v1"
    ]
    assert response.json()[0]["source_file"] == "SAML-D.csv"


def test_list_can_select_one_dataset_type():
    with _client() as client:
        response = client.get("/datasets?dataset_type=primary")

    assert response.status_code == 200
    assert [item["dataset_type"] for item in response.json()] == ["primary"]


def test_catalog_summary_uses_metadata_without_loading_transactions():
    with _client() as client:
        response = client.get("/datasets/summary")

    assert response.status_code == 200
    assert response.json() == {
        "registered": 3,
        "active": 2,
        "primary": 1,
        "knowledge": 1,
        "kyc": 1,
        "governed_rows": 14_250,
        "labelled_laundering_rows": 420,
    }


def test_dataset_detail_is_exact_and_invalid_identifiers_are_rejected():
    with _client() as client:
        detail = client.get("/datasets/ibm-hi-small-v1")
        missing = client.get("/datasets/unknown-v1")
        invalid = client.get("/datasets/not%20safe")

    assert detail.status_code == 200
    assert detail.json()["source_file"] == "HI-Small_Trans.csv"
    assert missing.status_code == 404
    assert invalid.status_code == 422


def test_repository_failures_return_a_stable_service_error():
    class FailingRepository(FakeDatasetRepository):
        def list_datasets(self):
            raise RuntimeError("database path and credentials must stay private")

    with _client(FailingRepository()) as client:
        response = client.get("/datasets")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "The governed dataset catalog is temporarily unavailable."
    }
    assert "credentials" not in response.text
