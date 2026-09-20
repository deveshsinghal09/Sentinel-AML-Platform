"""Notify only after the existing engine classifies an entity as high risk."""
from api.services.aws import settings
from api.services.aws.logging import event


class SNSService:
    def __init__(self, topic_arn=None, client=None):
        self.topic_arn = topic_arn
        self.client = client

    def notify_high_risk(self, response):
        high = [entity for entity in response.top_entities if entity.risk_label == "high"]
        if not high:
            return {"status": "not_required"}
        event("high_risk_detected", investigation_id=response.investigation_id,
              dataset_id=response.dataset_id, risk_score=max(entity.risk_score for entity in high))
        event("sns_notification_attempted", investigation_id=response.investigation_id)
        try:
            topic = self.topic_arn or settings.required("AWS_SNS_TOPIC_ARN")
            client = self.client or settings.client("sns")
            lines = ["HIGH RISK AML ALERT", f"Investigation ID: {response.investigation_id}",
                     f"High-risk entities: {len(high)}"]
            for entity in high[:10]:
                lines.extend([f"Account: {entity.entity_id}", f"Risk Score: {entity.risk_score:.4f}",
                              "Risk Level: HIGH", "Signals: " + ", ".join(entity.rule_flags)[:2000],
                              f"Recommended Action: {entity.escalation_action}"])
            result = client.publish(TopicArn=topic, Subject="HIGH RISK AML ALERT",
                                    Message="\n".join(lines))
            message_id = result.get("MessageId")
            if not message_id:
                raise RuntimeError("SNS did not confirm publication")
            event("sns_notification_sent", investigation_id=response.investigation_id)
            return {"status": "sent", "message_id": message_id}
        except Exception as exc:
            event("sns_notification_failed", investigation_id=response.investigation_id,
                  error_type=type(exc).__name__)
            return {"status": "failed"}
