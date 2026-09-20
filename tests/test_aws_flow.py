"""Real ingestion/AML/report/workflow pipeline; only AWS network I/O is mocked."""
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from api.services.aws.s3_service import S3Service
from scripts.create_aws_demo import create_demo


class MemoryS3:
    def __init__(self):
        self.objects = {}

    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        content = self.objects[Key]
        return {"ETag": hashlib.md5(content).hexdigest(), "ContentLength": len(content), "Metadata": {}}

    def upload_file(self, path, bucket, key, ExtraArgs):
        self.objects[key] = Path(path).read_bytes()

    def download_file(self, bucket, key, path):
        Path(path).write_bytes(self.objects[key])

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body


class MemoryTable:
    def __init__(self):
        self.items = {}
        self.fail_next_put = False

    def put_item(self, Item, **kwargs):
        from botocore.exceptions import ClientError
        key = Item["investigation_id"]
        if self.fail_next_put and key != "__sentinel_workspace_lock__":
            self.fail_next_put = False
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "PutItem")
        if key in self.items:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.items[key] = Item.copy()

    def get_item(self, Key, **kwargs):
        item = self.items.get(Key["investigation_id"])
        return {"Item": item.copy()} if item else {}

    def delete_item(self, Key, **kwargs):
        self.items.pop(Key["investigation_id"], None)

    def update_item(self, Key, ExpressionAttributeNames, ExpressionAttributeValues, **kwargs):
        item = self.items[Key["investigation_id"]]
        for index, field in enumerate(ExpressionAttributeNames.values()):
            item[field] = ExpressionAttributeValues[f":v{index}"]
        return {"Attributes": item.copy()}


@pytest.mark.parametrize("sns_fails,dynamodb_fails_once,extension", [
    (False, False, "csv"), (True, False, "csv"),
    (False, True, "csv"), (True, True, "csv"), (False, False, "xlsx"),
])
def test_real_aml_s3_to_dynamodb_sns_report_and_cold_restore(tmp_path, monkeypatch, sns_fails, dynamodb_fails_once, extension):
    from api.services.aws import settings
    import boto3
    import config
    import tools.data_loader as loader
    from api.services.aws.runtime import restore, sync_investigations
    from api.services.aws.investigations import get
    from lambda_handler import handler
    from tools.ml_engine import clear_model_cache

    database, upload = create_demo(tmp_path)
    if extension == "xlsx":
        import pandas as pd
        frame = pd.read_csv(upload)
        upload = upload.with_suffix(".xlsx")
        frame.to_excel(upload, index=False)
    monkeypatch.setattr(config, "DB_PATH", database)
    monkeypatch.setattr(loader, "DB_PATH", database)
    monkeypatch.setenv("AWS_ENABLED", "true")
    monkeypatch.setenv("AWS_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_DYNAMODB_TABLE", "investigations")
    monkeypatch.setenv("AWS_SNS_TOPIC_ARN", "topic")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DB_PATH", str(database))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    s3, table, sns = MemoryS3(), MemoryTable(), Mock()
    table.fail_next_put = dynamodb_fails_once
    sns.publish.return_value = {"MessageId": "real-sdk-response-mocked-in-test"}
    if sns_fails:
        sns.publish.side_effect = RuntimeError("SNS unavailable")
    monkeypatch.setattr(settings, "client", lambda service: {"s3": s3, "sns": sns}[service])
    resource = Mock()
    resource.Table.return_value = table
    monkeypatch.setattr(boto3, "resource", Mock(return_value=resource))
    key = f"datasets/demo/transactions.{extension}"
    s3.objects[key] = upload.read_bytes()
    s3.objects["state/workspace.duckdb"] = database.read_bytes()
    event = {"Records": [{"eventSource": "aws:s3", "eventName": "ObjectCreated:Put",
                          "s3": {"bucket": {"name": "bucket"}, "object": {
                              "key": key, "eTag": hashlib.md5(upload.read_bytes()).hexdigest()}}}]}
    clear_model_cache()
    context = SimpleNamespace(aws_request_id="test-request")
    if dynamodb_fails_once:
        with pytest.raises(RuntimeError, match="retry_required"):
            handler(event, context)
    result = handler(event, context)
    investigation_id = result["results"][0]["investigation_id"]
    item = table.items[investigation_id]
    assert item["risk_level"] == "high"
    assert item["notification_status"] == ("failed" if sns_fails else "sent")
    assert "response" not in item  # never store transaction evidence in DynamoDB
    assert s3.objects[item["report_s3_key"]].startswith(b"%PDF")
    assert any(key.startswith("sar-drafts/") for key in s3.objects)
    response = get(investigation_id).response
    assert {"rule_engine", "statistical", "ml_engine", "risk_scorer"}.issubset(response.plan.steps)
    publish_attempts = sns.publish.call_count
    assert publish_attempts >= 1
    if not sns_fails:
        sns.publish.assert_called_once()
    assert handler(event, context)["results"][0]["duplicate"]
    assert sns.publish.call_count == publish_attempts
    from tools.workflow_store import list_queue, assign_alert
    from api.services.aws.runtime import checkpoint
    alert = list_queue()[0]
    assign_alert(alert.alert_id, "demo.investigator", "demo.supervisor")
    assert table.items[investigation_id]["assigned_to"] == "demo.investigator"
    assert get(investigation_id).status == "in_review"
    checkpoint()
    # Discard the local cache, then prove durable state survives a cold start.
    database.unlink()
    restore()
    sync_investigations()
    assert get(investigation_id).response.summary_stats.high_risk > 0
    assert get(investigation_id).status == "in_review"
    clear_model_cache()


def test_ingest_baselines_downloads_s3_sources_then_uses_restored_tables(tmp_path, monkeypatch):
    from api.services.aws.bootstrap import ingest_baselines
    from api.services.aws import settings
    import tools.data_loader as loader

    create_demo(tmp_path / "input")
    monkeypatch.setattr(loader, "DB_PATH", tmp_path / "fresh.duckdb")
    monkeypatch.setenv("AWS_S3_BUCKET", "bucket")
    s3 = MemoryS3()
    s3.objects["state/bootstrap/transactions.csv"] = (tmp_path / "input/synthetic-normal.csv").read_bytes()
    s3.objects["state/bootstrap/knowledge.csv"] = (tmp_path / "input/synthetic-knowledge.csv").read_bytes()
    monkeypatch.setattr(settings, "client", lambda service: s3)
    assert ingest_baselines() == {"status": "ok", "transactions": 200, "saml_knowledge": 200}
    s3.objects.clear()
    assert ingest_baselines() == {"status": "ok", "transactions": 200, "saml_knowledge": 200}


def test_api_gateway_upload_then_s3_analysis_and_binary_report(tmp_path, monkeypatch):
    import base64
    import boto3
    import httpx
    import config
    import api.main as api
    import tools.data_loader as loader
    from api.services.aws import settings
    from lambda_handler import handler
    from tests.test_aws_lambda import http_event

    database, upload = create_demo(tmp_path)
    for module in (config, loader, api):
        monkeypatch.setattr(module, "DB_PATH", database)
    monkeypatch.setattr(api, "UPLOAD_DIR", tmp_path / "uploads")
    for key, value in {"AWS_ENABLED": "true", "AWS_S3_BUCKET": "bucket",
                       "AWS_DYNAMODB_TABLE": "table", "AWS_SNS_TOPIC_ARN": "topic",
                       "DATA_DIR": str(tmp_path), "DB_PATH": str(database),
                       "UPLOAD_DIR": str(tmp_path / "uploads")}.items():
        monkeypatch.setenv(key, value)
    s3, table, sns = MemoryS3(), MemoryTable(), Mock()
    sns.publish.return_value = {"MessageId": "test-message"}
    monkeypatch.setattr(settings, "client", lambda service: {"s3": s3, "sns": sns}[service])
    resource = Mock()
    resource.Table.return_value = table
    monkeypatch.setattr(boto3, "resource", Mock(return_value=resource))
    s3.objects["state/workspace.duckdb"] = database.read_bytes()
    context = SimpleNamespace(aws_request_id="test-request")
    request = httpx.Request("POST", "https://example/datasets/upload",
        files={"file": ("transactions.csv", upload.read_bytes(), "text/csv")},
        data={"display_name": "AWS upload", "dataset_type": "primary"})
    event = http_event("/datasets/upload")
    event["requestContext"]["http"]["method"] = "POST"
    event["headers"].update(dict(request.headers))
    event["isBase64Encoded"] = True
    event["body"] = base64.b64encode(request.read()).decode()
    uploaded = handler(event, context)
    assert uploaded["statusCode"] == 200
    dataset_id = json.loads(uploaded["body"])["dataset_id"]
    key = f"datasets/{dataset_id}/transactions.csv"
    assert s3.objects[key] == upload.read_bytes()
    metadata = json.loads(s3.objects[f"state/datasets/{dataset_id}.json"])
    assert metadata["s3_key"] == key
    assert metadata["filename"] == "transactions.csv"
    assert metadata["uploaded_at"]
    assert not list((tmp_path / "uploads").glob("*"))
    # Simulate the ObjectCreated notification emitted by the real S3 service.
    notification = {"Records": [{"eventSource": "aws:s3", "eventName": "ObjectCreated:Put",
        "s3": {"bucket": {"name": "bucket"}, "object": {
            "key": key, "eTag": hashlib.md5(s3.objects[key]).hexdigest()}}}]}
    result = handler(notification, context)
    investigation_id = result["results"][0]["investigation_id"]
    detail = handler(http_event(f"/investigations/{investigation_id}"), context)
    assert detail["statusCode"] == 200
    assert json.loads(detail["body"])["response"]["summary_stats"]["high_risk"] > 0
    report = handler(http_event(f"/export/investigation/{investigation_id}"), context)
    assert report["statusCode"] == 200
    assert report["isBase64Encoded"] is True
    assert base64.b64decode(report["body"]).startswith(b"%PDF")
    assert any(key.startswith("reports/exports/") for key in s3.objects)
