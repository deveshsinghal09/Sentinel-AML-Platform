"""Investigation metadata in DynamoDB, large evidence payloads in S3."""
import json
import os
from datetime import datetime, timezone
from decimal import Decimal

from api.services.aws import settings
from api.services.aws.logging import event


def _values(value):
    return json.loads(json.dumps(value, default=str), parse_float=Decimal)


class InvestigationRepository:
    def __init__(self, table=None):
        if table is None:
            import boto3
            table = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "ap-south-1")).Table(
                settings.required("AWS_DYNAMODB_TABLE"))
        self.table = table

    def create_investigation(self, record):
        from botocore.exceptions import ClientError
        try:
            self.table.put_item(Item=_values(record),
                                ConditionExpression="attribute_not_exists(investigation_id)")
            event("dynamodb_write_success", investigation_id=record["investigation_id"])
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            event("dynamodb_write_failed", error_type=type(exc).__name__)
            raise
        return True

    def get_investigation(self, investigation_id):
        return self.table.get_item(Key={"investigation_id": investigation_id},
                                   ConsistentRead=True).get("Item")

    def list_investigations(self, limit=50, dataset_id=None):
        # Small hackathon table; paginate fully before sorting, never truncate a scan page.
        items, args = [], {"ConsistentRead": True}
        while True:
            page = self.table.scan(**args)
            items.extend(item for item in page.get("Items", [])
                         if item.get("kind") == "investigation"
                         and (dataset_id is None or item.get("dataset_id") == dataset_id))
            if not page.get("LastEvaluatedKey"):
                break
            args["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return sorted(items, key=lambda item: item["created_at"], reverse=True)[:limit]

    def update_investigation(self, investigation_id, changes):
        if not changes or "investigation_id" in changes:
            raise ValueError("Supply mutable investigation fields")
        names = {f"#f{i}": key for i, key in enumerate(changes)}
        values = {f":v{i}": _values(value) for i, value in enumerate(changes.values())}
        try:
            result = self.table.update_item(
                Key={"investigation_id": investigation_id},
                UpdateExpression="SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(changes))),
                ExpressionAttributeNames=names, ExpressionAttributeValues=values,
                ConditionExpression="attribute_exists(investigation_id)", ReturnValues="ALL_NEW")
            event("dynamodb_write_success", investigation_id=investigation_id)
            return result.get("Attributes", {})
        except Exception as exc:
            event("dynamodb_write_failed", investigation_id=investigation_id, error_type=type(exc).__name__)
            raise

    def update_status(self, investigation_id, status):
        if status not in {"open", "in_review", "escalated", "closed"}:
            raise ValueError("Invalid investigation status")
        return self.update_investigation(investigation_id, {
            "status": status, "updated_at": datetime.now(timezone.utc).isoformat()})
