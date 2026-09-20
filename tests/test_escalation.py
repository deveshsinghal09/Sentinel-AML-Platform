from __future__ import annotations

import pandas as pd
import pytest

from tools.escalation import get_action, recommend


@pytest.mark.parametrize(
    ("risk", "action"),
    [
        (0.0, "monitor"),
        (0.39, "monitor"),
        (0.40, "flag_for_review"),
        (0.69, "flag_for_review"),
        (0.70, "report"),
        (1.0, "report"),
    ],
)
def test_escalation_boundaries(risk, action):
    assert get_action(risk) == action


def test_escalation_column_added_to_dataframe():
    result = recommend(pd.DataFrame({"risk_score": [0.2, 0.5, 0.8]}))
    assert list(result["escalation_action"]) == [
        "monitor",
        "flag_for_review",
        "report",
    ]
