from __future__ import annotations

import pytest

from agent.visualization.chart_advisor import VisualizationAdvisorAgent


def test_targeted_results_prioritize_ranked_evidence_and_risk_view():
    advice = VisualizationAdvisorAgent().advise(
        {
            "top_entities": [
                {
                    "entity_id": "C-1",
                    "risk_score": 0.9,
                    "top_transactions": [
                        {"timestamp": "2026-06-01T09:00:00Z", "amount": 9800}
                    ],
                }
            ],
            "execution_trace": [{"tool": "rule_engine", "status": "run"}],
        }
    )

    ids = [item.chart_id for item in advice.recommendations]
    assert ids[:2] == ["suspicious-results", "risk-distribution"]
    assert "activity-timeline" in ids
    assert "counterparty-network" not in ids


def test_aggregation_query_uses_exact_table_instead_of_risk_chart():
    advice = VisualizationAdvisorAgent().advise(
        {
            "top_entities": [],
            "aggregation": {
                "rows": [{"entity_id": "C-1", "txn_count": 12}]
            },
        }
    )

    assert [item.chart_id for item in advice.recommendations] == [
        "aggregation-results"
    ]


def test_network_is_recommended_only_when_graph_evidence_is_present():
    advice = VisualizationAdvisorAgent().advise(
        {
            "graph": {
                "status": "ok",
                "nodes": [{"id": "A"}],
                "edges": [{"source": "A", "target": "B"}],
            }
        }
    )

    assert advice.recommendations[0].chart_id == "counterparty-network"
    assert not any("Network skipped" in item for item in advice.skipped)


@pytest.mark.parametrize("limit", [0, 7])
def test_chart_count_is_bounded(limit):
    with pytest.raises(ValueError, match="between 1 and 6"):
        VisualizationAdvisorAgent().advise({}, max_charts=limit)
