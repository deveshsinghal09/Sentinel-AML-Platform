"""Post-analysis side effects; notification failure never discards AML results."""
from api.services.aws.dynamodb_service import InvestigationRepository
from api.services.aws.logging import event


def complete(response):
    from api.services.aws.artifacts import store_reports
    from api.services.aws.sns_service import SNSService

    repository = InvestigationRepository()
    item = repository.get_investigation(response.investigation_id)
    if not item:
        raise RuntimeError("Persist investigation before completion")
    if item.get("notification_status") not in {"sent", "not_required"}:
        notification = SNSService().notify_high_risk(response)
        # An SNS publish can succeed even if this update fails. Standard SNS is
        # at-least-once; consumers should deduplicate by investigation ID.
        try:
            repository.update_investigation(response.investigation_id, {
                "notification_status": notification["status"],
                "sns_message_id": notification.get("message_id"),
            })
        except Exception as exc:
            event("notification_status_write_failed", investigation_id=response.investigation_id,
                  error_type=type(exc).__name__)
    if not item.get("report_s3_key"):
        key = store_reports(response)
        repository.update_investigation(response.investigation_id, {"report_s3_key": key})
    event("investigation_completed", investigation_id=response.investigation_id,
          dataset_id=response.dataset_id)
