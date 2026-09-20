"""Bridge existing Pydantic records to durable AWS storage."""
import json
from contextvars import ContextVar

from agent.models import InvestigationRecord, InvestigationSummary
from api.services.aws.dynamodb_service import InvestigationRepository
from api.services.aws.s3_service import S3Service

event_investigation_id = ContextVar("event_investigation_id", default=None)


def save(record):
    payload = record.model_dump(mode="json")
    response = payload.pop("response")
    key = f"reports/{record.investigation_id}/response.json"
    S3Service().put_bytes(json.dumps(response).encode(), key, "application/json")
    entities = record.response.top_entities
    highest = max(entities, key=lambda entity: entity.risk_score, default=None)
    item = {**payload, "kind": "investigation", "response_s3_key": key,
            "risk_score": highest.risk_score if highest else 0,
            "risk_level": highest.risk_label if highest else "low",
            "account_id": highest.entity_id if highest else None,
            "recommended_action": highest.escalation_action if highest else "monitor",
            "signals": highest.rule_flags if highest else [], "notification_status": "pending"}
    InvestigationRepository().create_investigation(item)


def summary(item):
    return InvestigationSummary.model_validate({
        key: value for key, value in item.items() if key in InvestigationSummary.model_fields})


def get(investigation_id):
    item = InvestigationRepository().get_investigation(investigation_id)
    if not item:
        return None
    with S3Service().temporary_file(item["response_s3_key"]) as path:
        response = json.loads(path.read_text(encoding="utf-8"))
    return InvestigationRecord(**summary(item).model_dump(), response=response)


def list_records(limit=50, dataset_id=None):
    return [summary(item) for item in InvestigationRepository().list_investigations(limit, dataset_id)]


def sync_workflow(record):
    InvestigationRepository().update_investigation(record.investigation_id, {
        "status": record.status, "disposition": record.disposition,
        "updated_at": record.updated_at,
    })
