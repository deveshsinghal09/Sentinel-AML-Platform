from __future__ import annotations

from datetime import UTC, datetime

import duckdb
import pytest

from api.repositories.workflow_repository import WorkflowRepository


def _repository(tmp_path):
    database = tmp_path / "workflow-regression.duckdb"
    repository = WorkflowRepository(lambda: duckdb.connect(str(database)))
    repository.queue_summary()
    with duckdb.connect(str(database)) as connection:
        for alert_id, status in (("ALT-001", "new"), ("ALT-002", "closed")):
            connection.execute(
                """
                INSERT INTO governed_alert_queue
                VALUES (?, ?, ?, 0.8, 'high', 'report', 'structuring',
                        ?, 4, NULL, ?, 'pending', '')
                """,
                [
                    alert_id,
                    f"ACC-{alert_id[-1]}",
                    "INV-001",
                    datetime.now(UTC).replace(tzinfo=None),
                    status,
                ],
            )
    return repository


def test_queue_filters_are_parameterized_against_injection(tmp_path):
    repository = _repository(tmp_path)

    rows, total = repository.list_alerts(
        status="new' OR 1=1 --",
        assigned_to=None,
        limit=100,
        offset=0,
    )
    all_rows, all_total = repository.list_alerts(
        status=None,
        assigned_to=None,
        limit=100,
        offset=0,
    )

    assert rows == []
    assert total == 0
    assert len(all_rows) == all_total == 2


def test_notes_append_and_generate_distinct_immutable_audit_events(tmp_path):
    repository = _repository(tmp_path)

    first = repository.append_note("ALT-001", "First review", "analyst@bank.test")
    second = repository.append_note("ALT-001", "Second review", "analyst@bank.test")
    events, total = repository.list_audit(
        alert_id="ALT-001",
        limit=10,
        offset=0,
    )

    assert "First review" in second["notes"]
    assert "Second review" in second["notes"]
    assert first["notes"] != second["notes"]
    assert total == 2
    assert len({event["event_id"] for event in events}) == 2
    assert all(event["event_type"] == "alert_note_added" for event in events)


def test_missing_alert_rolls_back_without_audit_side_effect(tmp_path):
    repository = _repository(tmp_path)

    with pytest.raises(KeyError):
        repository.assign("ALT-404", "Avery", "supervisor@bank.test")

    events, total = repository.list_audit(
        alert_id=None,
        limit=10,
        offset=0,
    )
    assert events == []
    assert total == 0
