from __future__ import annotations

import csv
import io
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import exports


RECORD = {
    "investigation_id": "INV-001",
    "dataset_id": "primary-v1",
    "dataset_name": "Primary evidence",
    "query": "Find structuring",
    "status": "open",
    "response": {
        "query": "Find structuring",
        "plan": {
            "steps": ["data_loader", "rule_engine"],
            "reasoning": "Targeted structuring analysis.",
        },
        "summary_stats": {
            "total_analyzed": 120,
            "flagged": 1,
            "high_risk": 1,
        },
        "top_entities": [
            {
                "entity_id": "=CMD()",
                "risk_score": 0.91,
                "risk_label": "high",
                "escalation_action": "report",
                "saml_d_typology": "structuring",
                "txn_count": 8,
                "total_amount": 78_400,
                "explanation": "Eight sub-threshold transactions.",
                "citation": "https://www.fincen.gov/guidance",
            }
        ],
        "execution_trace": [
            {
                "tool": "data_loader",
                "status": "run",
                "duration_ms": 12.5,
                "reason": "Filtered load",
            }
        ],
    },
}


class Repository:
    def get_investigation(self, investigation_id):
        return RECORD if investigation_id == "INV-001" else None


def _client(repository=None):
    app = FastAPI()
    app.include_router(exports.router)
    app.dependency_overrides[exports.get_investigation_repository] = (
        lambda: repository or Repository()
    )
    app.dependency_overrides[exports.require_export_access] = lambda: object()
    return TestClient(app)


def test_json_investigation_export_is_private_attributable_and_downloadable():
    with _client() as client:
        response = client.get(
            "/exports/investigations/INV-001",
            params={"format": "json"},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-sentinel-investigation-id"] == "INV-001"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "investigation_INV-001.json" in response.headers["content-disposition"]
    assert response.json()["response"]["summary_stats"]["flagged"] == 1


def test_markdown_report_reconciles_plan_and_summary():
    with _client() as client:
        response = client.get(
            "/exports/investigations/INV-001",
            params={"format": "md"},
        )

    assert response.status_code == 200
    assert "Targeted structuring analysis." in response.text
    assert "1. data_loader" in response.text
    assert "- High risk: 1" in response.text
    assert "Authorized AML review is required" in response.text


def test_entity_csv_prevents_spreadsheet_formula_execution():
    with _client() as client:
        response = client.get(
            "/exports/investigations/INV-001/entities",
            params={"format": "csv"},
        )

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["entity_id"] == "'=CMD()"
    assert rows[0]["risk_score"] == "0.91"


def test_trace_json_contains_only_execution_evidence():
    with _client() as client:
        response = client.get(
            "/exports/investigations/INV-001/trace",
            params={"format": "json"},
        )

    assert json.loads(response.text) == RECORD["response"]["execution_trace"]
    assert "top_entities" not in response.text


def test_missing_record_and_unsupported_format_are_safe():
    with _client() as client:
        missing = client.get(
            "/exports/investigations/INV-404",
            params={"format": "json"},
        )
        unsupported = client.get(
            "/exports/investigations/INV-001",
            params={"format": "pdf"},
        )

    assert missing.status_code == 404
    assert unsupported.status_code == 422
