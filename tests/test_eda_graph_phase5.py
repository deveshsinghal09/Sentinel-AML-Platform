"""Phase 5 coverage for EDA payloads and bounded graph topology detection."""
from __future__ import annotations

import json

import pandas as pd

from agent.models import AgentResponse, IntentResult, PlanResult
from tools.eda import run_eda
from tools.graph_tool import run_graph


def _transactions() -> pd.DataFrame:
    edges = [
        ("A", "B"),
        ("B", "C"),
        ("C", "A"),
        ("D", "H"),
        ("E", "H"),
        ("F", "H"),
        ("H", "I"),
        ("H", "J"),
        ("H", "K"),
        ("U1", "V1"),
        ("U1", "V2"),
        ("U2", "V1"),
        ("U2", "V2"),
        ("S", "M1"),
        ("S", "M2"),
        ("S", "M3"),
        ("M1", "T"),
        ("M2", "T"),
        ("M3", "T"),
    ]
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2026-01-01",
                periods=len(edges),
                freq="12h",
            ),
            "from_account": [source for source, _ in edges],
            "to_account": [target for _, target in edges],
            "amount_paid": [float(index * 100) for index in range(1, 20)],
            "payment_format": ["Wire"] * len(edges),
            "is_laundering": [0] * 18 + [1],
        }
    )


def test_eda_returns_json_safe_summary_and_reviewer_chart_suite():
    frame = _transactions()

    result = run_eda(frame, filters={"payment_format": "Wire"})

    assert result["summary_stats"]["row_count"] == len(frame)
    assert result["summary_stats"]["unique_from_accounts"] > 0
    assert result["summary_stats"]["filters"]["payment_format"] == "Wire"
    assert [chart["chart_id"] for chart in result["charts"]] == [
        "amount_histogram",
        "transactions_over_time",
        "payment_format_distribution",
        "sender_country_breakdown",
        "customer_volume_distribution",
        "amount_percentiles",
        "risk_label_distribution",
        "typology_frequency",
        "hour_of_day_heatmap",
        "missing_data_assessment",
    ]
    assert sum(result["charts"][1]["data"][0]["y"]) == len(frame)
    assert result["charts"][0]["meta"]["overflow_count"] >= 0
    json.dumps(result)


def test_empty_eda_is_honest_and_chart_free():
    result = run_eda(pd.DataFrame())

    assert result["summary_stats"]["row_count"] == 0
    assert result["charts"] == []


def test_graph_detects_required_topologies_without_fabrication():
    result = run_graph(_transactions())

    assert result["status"] == "ok"
    assert any(
        set(cycle["accounts"]) == {"A", "B", "C"}
        for cycle in result["cycles"]
    )
    assert any(item["account"] == "H" for item in result["fan_in"])
    assert any(item["account"] == "H" for item in result["fan_out"])
    assert any(item["hub"] == "H" for item in result["gather_scatter"])
    assert any(
        set(item["sources"]) == {"U1", "U2"}
        and {"V1", "V2"}.issubset(item["destinations"])
        for item in result["bipartite"]
    )
    assert any(
        item["source"] == "S"
        and item["destination"] == "T"
        and item["path_count"] == 3
        for item in result["scatter_gather"]
    )
    json.dumps(result)


def test_graph_reports_no_cycle_and_enforces_safety_limit():
    acyclic = pd.DataFrame(
        {
            "from_account": ["A", "B", "C"],
            "to_account": ["B", "C", "D"],
        }
    )

    result = run_graph(acyclic)
    skipped = run_graph(acyclic, max_edges=2)

    assert result["cycles"] == []
    assert "No circular transfers detected" in result["note"]
    assert skipped["status"] == "skipped"
    assert "safety limit" in skipped["note"]


def test_agent_response_exposes_phase5_outputs():
    response = AgentResponse(
        query="analyse",
        intent=IntentResult(intent="broad_eda", require_eda=True),
        plan=PlanResult(
            steps=["data_loader", "eda"],
            reasoning="Broad EDA requested.",
        ),
        execution_trace=[],
        eda_summary={"row_count": 1},
        charts=[{"data": [], "layout": {}}],
        graph={"status": "ok"},
    )

    payload = response.model_dump()
    assert payload["eda_summary"]["row_count"] == 1
    assert payload["charts"] is not None
    assert payload["graph"]["status"] == "ok"
