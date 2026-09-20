from __future__ import annotations

from datetime import date, timedelta

import pytest

from agent.intent_extractor import IntentExtractor


@pytest.fixture()
def extractor() -> IntentExtractor:
    return IntentExtractor(use_llm=False)


def test_structuring_query_maps_to_pattern_search(extractor):
    result = extractor.extract("Find structuring patterns")
    assert (result.intent, result.pattern_type) == ("pattern_search", "structuring")


def test_aggregation_query_maps_to_aggregation(extractor):
    result = extractor.extract("Which customers made 10+ transactions under $10,000?")
    assert result.intent == "aggregation"


def test_entity_lookup_query_maps_to_entity_lookup(extractor):
    result = extractor.extract("Is customer ID 4521 suspicious?")
    assert result.intent == "entity_lookup"


def test_broad_eda_query_maps_to_broad_eda(extractor):
    result = extractor.extract("Analyse this dataset for suspicious activity")
    assert result.intent == "broad_eda"


def test_broad_eda_sets_require_eda_true(extractor):
    result = extractor.extract("Run exploratory analysis on the dataset")
    assert result.require_eda and result.require_ml


def test_layering_sets_require_graph_true(extractor):
    assert extractor.extract("Find layering").require_graph


def test_pattern_search_sets_require_ml_true(extractor):
    assert extractor.extract("Find structuring").require_ml


def test_aggregation_does_not_set_require_ml(extractor):
    assert not extractor.extract("How many transactions are there?").require_ml


def test_last_30_days_extracts_date_range(extractor):
    result = extractor.extract("Find structuring in the last 30 days")
    assert result.filters.date_range == (
        (date.today() - timedelta(days=30)).isoformat(),
        date.today().isoformat(),
    )


def test_amount_under_10000_extracts_max_amount(extractor):
    result = extractor.extract("Which customers made transactions under $10,000?")
    assert result.filters.max_amount == 10_000


def test_entity_id_4521_extracts_entity(extractor):
    result = extractor.extract("Is customer ID 4521 suspicious?")
    assert result.entities == ["4521"]
    assert result.filters.entity_id == "4521"


def test_from_nigeria_extracts_high_risk_country(extractor):
    result = extractor.extract("Find transactions from Nigeria")
    assert result.filters.from_country == "NIGERIA"


def test_empty_query_raises_value_error(extractor):
    with pytest.raises(ValueError):
        extractor.extract("  ")


def test_ambiguous_query_defaults_to_pattern_search(extractor):
    assert extractor.extract("Investigate unusual behaviour").intent == "pattern_search"
