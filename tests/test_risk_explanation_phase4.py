"""Phase 4 risk, escalation, grounding, and explanation tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.escalation import get_action, recommend
from tools.explanation import (
    ExplanationGenerator,
    explain,
    numbers_are_grounded,
)
from tools.risk_scorer import score


def test_risk_weights_are_normalized_over_tools_that_ran():
    frame = pd.DataFrame(
        {
            "rule_score": [1.0, 1.0],
            "stat_score": [0.0, 0.0],
            "ml_score": [1.0, 1.0],
            "from_country": ["UK", "Turkey"],
            "to_country": ["UK", "UK"],
            "rule_flags": [[], ["high_risk_country"]],
        }
    )
    scored = score(
        frame,
        ran_tools={"rule_engine", "statistical"},
    )
    expected = 0.40 / (0.40 + 0.25)
    assert np.isclose(scored.iloc[0]["risk_score"], expected)
    assert np.isclose(scored.iloc[1]["risk_score"], expected + 0.10)
    assert scored.iloc[0]["risk_label"] == "medium"
    assert scored.iloc[1]["risk_label"] == "high"
    assert (scored["active_detector_count"] == 2).all()


def test_rule_only_plan_is_not_diluted():
    frame = pd.DataFrame({"rule_score": [0.2, 0.8]})
    scored = score(frame, ran_tools={"rule_engine"})
    assert np.allclose(scored["risk_score"], [0.2, 0.8])
    assert scored["risk_label"].tolist() == ["low", "high"]


def test_risk_label_boundaries():
    frame = pd.DataFrame({"rule_score": [0.3499, 0.35, 0.6999, 0.70]})
    labels = score(frame, ran_tools={"rule_engine"})["risk_label"].tolist()
    assert labels == ["low", "medium", "medium", "high"]


def test_escalation_boundaries_and_pep_override():
    assert get_action(0.3999) == "monitor"
    assert get_action(0.40) == "flag_for_review"
    assert get_action(0.6999) == "flag_for_review"
    assert get_action(0.70) == "report"

    frame = pd.DataFrame(
        {
            "risk_score": [0.1, 0.4, 0.7],
            "rule_flags": [["pep"], [], []],
        }
    )
    assert recommend(frame)["escalation_action"].tolist() == [
        "report",
        "flag_for_review",
        "report",
    ]


def _explanation_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "from_account": ["A", "A", "B"],
            "to_account": ["X", "Y", "Z"],
            "amount_paid": [9_000.0, 9_100.0, 100.0],
            "txn_count_7d": [3, 4, 1],
            "near_threshold_count": [3, 4, 0],
            "rule_flags": [
                ["structuring"],
                ["structuring"],
                [],
            ],
            "rule_score": [1.0, 1.0, 0.0],
            "stat_score": [0.2, 0.3, 0.0],
            "ml_score": [0.7, 0.9, 0.0],
            "risk_score": [0.8, 0.9, 0.1],
            "risk_label": ["high", "high", "low"],
            "escalation_action": ["report", "report", "monitor"],
        }
    )


def test_offline_explanation_is_grounded_and_only_highest_entity_row():
    result = explain(
        _explanation_frame(),
        intent_result={"pattern_type": "structuring"},
        knowledge_snippets=[
            {
                "id": "structuring",
                "text": "Repeated sub-threshold transactions.",
            }
        ],
        generator=ExplanationGenerator(use_llm=False),
    )
    assert result.iloc[0]["explanation"] == ""
    assert result.iloc[1]["explanation"]
    assert result.iloc[1]["sar_draft"]
    assert result.iloc[1]["saml_d_typology"] == "Structuring"
    assert "31 U.S.C." in result.iloc[1]["citation"]
    assert result.iloc[2]["explanation"] == ""

    feature_json = {
        "entity_id": "A",
        "risk_score": 0.9,
        "rule_flags": ["structuring"],
    }
    combined = (
        result.iloc[1]["explanation"]
        + " "
        + result.iloc[1]["sar_draft"]
    )
    assert numbers_are_grounded(combined, feature_json)


def test_numeric_validator_rejects_unsupported_amount():
    features = {"entity_id": "A", "risk_score": 0.8, "txn_count_7d": 3}
    assert numbers_are_grounded("Risk score 0.8 from 3 transactions.", features)
    assert not numbers_are_grounded(
        "The entity transferred $12,345.",
        features,
    )


class SequenceCompletions:
    def __init__(self):
        self.calls = []
        self.outputs = [
            {
                "explanation": "Entity A transferred $12,345.",
                "sar_draft": "Risk score 0.8.",
                "citation": "invented",
            },
            {
                "explanation": "Entity A has grounded risk score 0.8.",
                "sar_draft": "Review entity A for Structuring.",
                "citation": "model supplied",
            },
        ]

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.outputs.pop(0)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(payload))
                )
            ]
        )


def test_llm_output_with_invented_number_is_regenerated_once():
    completions = SequenceCompletions()
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    generator = ExplanationGenerator(client=client, use_llm=True)
    result = explain(
        _explanation_frame().iloc[[0]].copy(),
        intent_result={"pattern_type": "structuring"},
        knowledge_snippets=[
            {
                "id": "structuring",
                "text": "Repeated sub-threshold transactions.",
            }
        ],
        generator=generator,
    )
    assert len(completions.calls) == 2
    assert "$12,345" not in result.iloc[0]["explanation"]
    assert "risk score 0.8" in result.iloc[0]["explanation"]
    assert "31 U.S.C." in result.iloc[0]["citation"]
    assert completions.calls[0]["model"] == "openai/gpt-oss-120b"
    assert completions.calls[0]["response_format"] == {
        "type": "json_object"
    }
