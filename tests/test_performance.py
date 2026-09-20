from __future__ import annotations

from time import perf_counter

import pytest

from agent.runner import AgentRunner
from tools.data_loader import load
from tools.escalation import recommend
from tools.feature_engineering import engineer_features
from tools.ml_engine import run_ml
from tools.risk_scorer import score
from tools.rule_engine import run_rules
from tools.statistical import run_statistical


pytestmark = [pytest.mark.performance, pytest.mark.requires_data]


@pytest.fixture(scope="module")
def sample_df_1000():
    return load(
        date_range=("2022-09-01", "2022-09-18"),
        limit=1_000,
    )


@pytest.fixture(scope="module")
def featured_df_1000(sample_df_1000):
    return engineer_features(sample_df_1000)


def test_data_loader_filter_under_1s():
    started = perf_counter()
    frame = load(
        date_range=("2022-09-01", "2022-09-18"),
        limit=1_000,
    )
    duration = perf_counter() - started
    assert len(frame) == 1_000
    assert duration < 1.0


def test_feature_engineering_1000_rows_under_2s(sample_df_1000):
    started = perf_counter()
    result = engineer_features(sample_df_1000)
    assert len(result) == 1_000
    assert perf_counter() - started < 2.0


def test_rule_engine_1000_rows_under_half_second(featured_df_1000):
    started = perf_counter()
    run_rules(featured_df_1000)
    assert perf_counter() - started < 0.5


def test_statistical_1000_rows_under_half_second(featured_df_1000):
    started = perf_counter()
    run_statistical(featured_df_1000)
    assert perf_counter() - started < 0.5


def test_ml_engine_1000_rows_under_5s(featured_df_1000):
    started = perf_counter()
    result = run_ml(featured_df_1000)
    assert len(result) == 1_000
    assert perf_counter() - started < 5.0


def test_full_pipeline_500_rows_under_10s():
    started = perf_counter()
    AgentRunner(use_llm=False, max_rows=500).run(
        "Find structuring patterns between 2022-09-01 and 2022-09-18"
    )
    assert perf_counter() - started < 10.0


def test_risk_scorer_and_escalation_1000_rows_under_point_2s(
    featured_df_1000,
):
    detected = run_rules(featured_df_1000)
    detected = run_statistical(detected)
    detected["ml_score"] = 0.0
    started = perf_counter()
    scored = score(
        detected,
        ran_tools={"rule_engine", "statistical", "ml_engine"},
    )
    recommend(scored)
    assert perf_counter() - started < 0.2
