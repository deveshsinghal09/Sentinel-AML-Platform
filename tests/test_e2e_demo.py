from __future__ import annotations

import os

import httpx
import pytest


BASE_URL = os.environ.get("SENTINEL_API_URL", "http://127.0.0.1:8000").rstrip("/")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("RUN_E2E") != "1",
        reason="Set RUN_E2E=1 to test a running Sentinel API.",
    ),
]

DEMO_QUERIES = [
    (
        "Find structuring patterns in the last 30 days",
        {"must_skip": ["eda", "graph_tool"], "must_run": ["rule_engine"]},
    ),
    (
        "Which customers made 10+ transactions under $10,000?",
        {
            "must_skip": [
                "eda",
                "feature_engineering",
                "ml_engine",
                "graph_tool",
            ],
            "must_run": ["aggregation"],
        },
    ),
    (
        "Is customer ID 4521 suspicious?",
        {"must_skip": ["eda", "graph_tool"], "must_run": ["rule_engine"]},
    ),
    (
        "Analyse this dataset for suspicious activity",
        {"must_skip": ["graph_tool"], "must_run": ["eda"]},
    ),
]


@pytest.mark.parametrize(("query", "expectations"), DEMO_QUERIES)
def test_demo_query_trace(query, expectations):
    response = httpx.post(
        f"{BASE_URL}/query",
        json={"query": query},
        timeout=30,
    )
    assert response.status_code == 200
    payload = response.json()
    ran = {
        step["tool"]
        for step in payload["execution_trace"]
        if step["status"] == "run"
    }
    skipped = {
        step["tool"]
        for step in payload["execution_trace"]
        if step["status"] == "skipped"
    }
    assert set(expectations["must_run"]).issubset(ran)
    assert set(expectations["must_skip"]).issubset(skipped)
