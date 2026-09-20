import json
from unittest.mock import Mock

import pytest

from aws.lambdas.s3_ingestion.handler import handler, parse_record


def record(key="datasets/ds_demo/transactions.csv", bucket="bucket"):
    return {"eventSource": "aws:s3", "eventName": "ObjectCreated:Put",
            "s3": {"bucket": {"name": bucket}, "object": {"key": key, "eTag": "abc"}}}


def test_missing_records_does_not_create_client():
    assert handler({})["reason"] == "missing_records"
    assert handler({"Records": []})["status"] == "ignored"


def test_url_encoded_event():
    parsed = parse_record(record("datasets/ds_demo/my+transactions%2Exlsx"), "bucket")
    assert parsed["key"] == "datasets/ds_demo/my transactions.xlsx"
    assert parsed["dataset_id"] == "ds_demo"


@pytest.mark.parametrize("key", ["reports/inv/report.pdf", "datasets/ds_demo/file.exe", "datasets/../bad.csv"])
def test_unsupported_event_ignored(key):
    assert parse_record(record(key), "bucket") is None


def test_wrong_bucket_rejected():
    with pytest.raises(ValueError, match="Unexpected"):
        parse_record(record(), "other")


def test_failed_batch_raises_for_lambda_retry(monkeypatch):
    import importlib
    module = importlib.import_module("aws.lambdas.s3_ingestion.handler")
    monkeypatch.setattr(module, "S3Service", lambda: Mock(bucket="bucket"))
    monkeypatch.setattr(module, "process_object", Mock(side_effect=RuntimeError("storage unavailable")))
    with pytest.raises(RuntimeError, match="retry_required"):
        handler({"Records": [record()]})


def test_completed_receipt_skips_analysis(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from aws.lambdas.s3_ingestion.handler import process_object
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"status": "completed", "investigation_id": "INV-existing"}))
    @contextmanager
    def temporary_file(key):
        yield receipt
    s3 = Mock()
    s3.temporary_file = temporary_file
    s3.file_exists.return_value = True
    result = process_object(parse_record(record(), "bucket"), s3)
    assert result["duplicate"] is True
    s3.client.head_object.assert_not_called()
