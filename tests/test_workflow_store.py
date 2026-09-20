from __future__ import annotations

import duckdb

from agent.models import (
    AgentResponse,
    ExecutionStep,
    FlaggedEntity,
    IntentResult,
    PlanResult,
    SummaryStats,
)
from tools.workflow_store import (
    append_alert_note,
    assign_alert,
    disposition_alert,
    get_investigation,
    list_audit_events,
    list_investigations,
    list_queue,
    persist_investigation,
    queue_summary,
)


def sample_response() -> AgentResponse:
    return AgentResponse(
        query="Find structuring patterns in the last 30 days",
        intent=IntentResult(
            intent="pattern_search",
            pattern_type="structuring",
        ),
        plan=PlanResult(
            steps=["data_loader", "feature_engineering", "rule_engine"],
            reasoning="A targeted query skips broad EDA.",
        ),
        execution_trace=[
            ExecutionStep(
                tool="data_loader",
                status="run",
                duration_ms=2.5,
                reason="Filtered slice required.",
            ),
            ExecutionStep(
                tool="eda",
                status="skipped",
                reason="Targeted query.",
            ),
        ],
        top_entities=[
            FlaggedEntity(
                entity_id="CUST-4521",
                risk_score=0.91,
                risk_label="high",
                escalation_action="report",
                saml_d_typology="Structuring",
                explanation="Repeated sub-threshold transfers.",
            )
        ],
        summary_stats=SummaryStats(
            total_analyzed=120,
            flagged=1,
            high_risk=1,
        ),
    )


def test_investigation_queue_and_audit_are_persisted_atomically():
    conn = duckdb.connect(":memory:")
    persisted = persist_investigation(sample_response(), conn=conn)

    assert persisted.investigation_id
    assert list_investigations(conn=conn)[0].alert_count == 1
    record = get_investigation(persisted.investigation_id, conn=conn)
    assert record is not None
    assert record.response.plan.reasoning == "A targeted query skips broad EDA."

    queue = list_queue(conn=conn)
    assert queue[0].entity_id == "CUST-4521"
    assert queue[0].sla_hours == 4
    assert queue_summary(conn=conn)["new"] == 1

    events, total = list_audit_events(conn=conn)
    assert total == len(events)
    assert {"query_received", "plan_created", "tool_executed", "tool_skipped", "alert_created", "investigation_completed"} <= {event.event_type for event in events}


def test_analyst_actions_update_queue_and_append_versioned_events():
    conn = duckdb.connect(":memory:")
    persisted = persist_investigation(sample_response(), conn=conn)
    alert_id = list_queue(conn=conn)[0].alert_id

    assigned = assign_alert(alert_id, "analyst.one", "supervisor", conn=conn)
    assert assigned is not None
    assert assigned.status == "in_review"
    assert assigned.assigned_to == "analyst.one"

    noted = append_alert_note(alert_id, "Verified counterparties.", "analyst.one", conn=conn)
    assert noted is not None
    assert "Verified counterparties." in noted.notes

    closed = disposition_alert(alert_id, "false_positive", "analyst.one", conn=conn)
    assert closed is not None
    assert closed.status == "closed"
    assert closed.disposition == "false_positive"
    record = get_investigation(persisted.investigation_id, conn=conn)
    assert record is not None and record.status == "closed"

    events, _ = list_audit_events(conn=conn)
    analyst_events = {event.event_type for event in events}
    assert {"alert_assigned", "analyst_note_added", "alert_dispositioned"} <= analyst_events
    assert all(event.risk_policy_version for event in events)
