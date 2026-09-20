from unittest.mock import Mock

import pytest

from api.services.aws.s3_service import S3Service


def test_s3_upload_and_download(tmp_path):
    client = Mock()
    s3 = S3Service("test-bucket", client)
    path = tmp_path / "transactions.csv"
    path.write_text("amount\n100\n")
    key = "datasets/ds_demo/transactions.csv"
    assert s3.upload_file(path, key) == key
    client.upload_file.assert_called_once_with(str(path), "test-bucket", key,
                                               ExtraArgs={"Metadata": {}})
    assert s3.download_file(key, path) == path
    client.download_file.assert_called_once_with("test-bucket", key, str(path))


def test_s3_temporary_download_cleans_up():
    client = Mock()
    client.download_file.side_effect = lambda bucket, key, path: __import__("pathlib").Path(path).write_text("data")
    with S3Service("bucket", client).temporary_file("datasets/id/file.xlsx") as path:
        assert path.exists()
    assert not path.exists()


def test_s3_access_denied_is_not_missing():
    from botocore.exceptions import ClientError
    client = Mock()
    client.head_object.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "HeadObject")
    with pytest.raises(ClientError):
        S3Service("bucket", client).file_exists("x")


def test_dynamodb_creation_converts_floats():
    from decimal import Decimal
    from api.services.aws.dynamodb_service import InvestigationRepository
    table = Mock()
    repository = InvestigationRepository(table)
    assert repository.create_investigation({"investigation_id": "INV-test", "risk_score": 0.86})
    assert table.put_item.call_args.kwargs["Item"]["risk_score"] == Decimal("0.86")
    assert "attribute_not_exists" in table.put_item.call_args.kwargs["ConditionExpression"]


def test_dynamodb_paginated_listing():
    from api.services.aws.dynamodb_service import InvestigationRepository
    table = Mock()
    table.scan.side_effect = [
        {"Items": [{"kind": "investigation", "created_at": "2025", "dataset_id": "a"}],
         "LastEvaluatedKey": {"investigation_id": "old"}},
        {"Items": [{"kind": "investigation", "created_at": "2026", "dataset_id": "a"}]},
    ]
    assert InvestigationRepository(table).list_investigations(1, "a")[0]["created_at"] == "2026"
    assert table.scan.call_count == 2


class _LockTable:
    def __init__(self, locked=False):
        self.item = ({"investigation_id": "__sentinel_workspace_lock__",
                      "lock_token": "other", "lock_expires_at": 9999999999}
                     if locked else None)

    def put_item(self, Item, **kwargs):
        from botocore.exceptions import ClientError
        if self.item is not None:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.item = Item

    def delete_item(self, Key, **kwargs):
        self.item = None


def test_workspace_lock_acquires_and_releases(monkeypatch):
    import boto3
    from api.services.aws.runtime import workspace_lock
    table, resource = _LockTable(), Mock()
    resource.Table.return_value = table
    monkeypatch.setenv("AWS_ENABLED", "true")
    monkeypatch.setenv("AWS_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_DYNAMODB_TABLE", "table")
    monkeypatch.setenv("AWS_SNS_TOPIC_ARN", "topic")
    monkeypatch.setattr(boto3, "resource", Mock(return_value=resource))
    with workspace_lock(request_id="request", wait_seconds=0):
        assert table.item["lock_token"] == "request"
    assert table.item is None


def test_workspace_lock_returns_busy_without_overwriting_owner(monkeypatch):
    import boto3
    from api.services.aws.runtime import WorkspaceBusy, workspace_lock
    table, resource = _LockTable(locked=True), Mock()
    resource.Table.return_value = table
    monkeypatch.setenv("AWS_ENABLED", "true")
    monkeypatch.setenv("AWS_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_DYNAMODB_TABLE", "table")
    monkeypatch.setenv("AWS_SNS_TOPIC_ARN", "topic")
    monkeypatch.setattr(boto3, "resource", Mock(return_value=resource))
    with pytest.raises(WorkspaceBusy):
        with workspace_lock(request_id="request", wait_seconds=0):
            pass
    assert table.item["lock_token"] == "other"


@pytest.mark.parametrize("level,expected", [("high", 1), ("medium", 0), ("low", 0)])
def test_sns_uses_existing_risk_label(level, expected):
    from types import SimpleNamespace
    from api.services.aws.sns_service import SNSService
    client = Mock()
    client.publish.return_value = {"MessageId": "message"}
    response = SimpleNamespace(investigation_id="INV-test", dataset_id="ds_test", top_entities=[
        SimpleNamespace(risk_label=level, risk_score=0.86, entity_id="account",
                        rule_flags=["structuring"], escalation_action="report")])
    result = SNSService("arn:aws:sns:ap-south-1:123456789012:alerts", client).notify_high_risk(response)
    assert client.publish.call_count == expected
    assert result["status"] == ("sent" if expected else "not_required")


@pytest.mark.parametrize("failure", ["exception", "missing_message_id"])
def test_sns_failure_is_nonfatal(failure):
    from types import SimpleNamespace
    from api.services.aws.sns_service import SNSService
    client = Mock()
    if failure == "exception":
        client.publish.side_effect = RuntimeError("unavailable")
    else:
        client.publish.return_value = {}
    response = SimpleNamespace(investigation_id="INV-test", dataset_id="ds_test", top_entities=[
        SimpleNamespace(risk_label="high", risk_score=0.9, entity_id="account",
                        rule_flags=[], escalation_action="report")])
    assert SNSService("topic", client).notify_high_risk(response) == {"status": "failed"}
