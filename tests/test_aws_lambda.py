import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


def http_event(path="/health"):
    return {"version": "2.0", "routeKey": "ANY /{proxy+}", "rawPath": path,
            "rawQueryString": "", "headers": {"host": "example.execute-api.ap-south-1.amazonaws.com"},
            "requestContext": {"stage": "$default", "requestId": "test-request", "http": {
                "method": "GET", "path": path, "sourceIp": "127.0.0.1", "protocol": "HTTP/1.1"}},
            "isBase64Encoded": False}


def test_real_fastapi_health_through_mangum():
    from mangum import Mangum
    from api.main import app
    result = Mangum(app, lifespan="off")(http_event(), SimpleNamespace())
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["status"] == "ok"


def test_restore_failure_returns_503_without_overwriting_snapshot(monkeypatch):
    import lambda_handler
    from api.services.aws import runtime
    for key, value in {"AWS_ENABLED": "false", "DATA_DIR": "dataset", "DB_PATH": "dataset/aml.duckdb",
                       "UPLOAD_DIR": "dataset/uploads"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(runtime, "restore", Mock(side_effect=RuntimeError("S3 unavailable")))
    checkpoint = Mock()
    monkeypatch.setattr(runtime, "checkpoint", checkpoint)
    result = lambda_handler.handler(http_event("/ready"), SimpleNamespace(aws_request_id="request"))
    assert result["statusCode"] == 503
    checkpoint.assert_not_called()


def test_lambda_health_bypasses_unavailable_storage(monkeypatch):
    import lambda_handler
    from api.services.aws import runtime
    for key, value in {"AWS_ENABLED": "false", "DATA_DIR": "dataset", "DB_PATH": "dataset/aml.duckdb",
                       "UPLOAD_DIR": "dataset/uploads"}.items():
        monkeypatch.setenv(key, value)
    restore = Mock(side_effect=RuntimeError("S3 unavailable"))
    monkeypatch.setattr(runtime, "restore", restore)
    result = lambda_handler.handler(http_event(), SimpleNamespace(aws_request_id="request"))
    assert result["statusCode"] == 200
    restore.assert_not_called()


@pytest.mark.parametrize("suffix,expected_type", [
    ("?format=json", "application/json"),
    ("?format=md", "text/markdown"),
    ("/entities?format=csv", "text/csv"),
    ("/trace?format=json", "application/json"),
])
def test_frontend_export_paths_use_existing_generators(tmp_path, monkeypatch, suffix, expected_type):
    import duckdb
    from fastapi.testclient import TestClient
    from api.main import app
    from tools.workflow_store import persist_investigation
    from tests.test_workflow_store import sample_response
    monkeypatch.setenv("AWS_ENABLED", "false")
    monkeypatch.setattr("tools.workflow_store.get_db_connection",
                        lambda: duckdb.connect(str(tmp_path / "workflow.duckdb")))
    response = persist_investigation(sample_response())
    result = TestClient(app).get(f"/exports/investigations/{response.investigation_id}{suffix}")
    assert result.status_code == 200
    assert result.headers["content-type"].startswith(expected_type)


def test_aws_sdk_error_is_safe_and_retryable():
    from botocore.exceptions import ClientError
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.services.aws.errors import install_exception_handlers
    application = FastAPI()
    install_exception_handlers(application)
    @application.get("/evidence")
    def evidence():
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "sensitive data"}}, "GetObject")
    response = TestClient(application).get("/evidence")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "2"
    assert "sensitive data" not in response.text


def test_invalid_xlsx_returns_422_and_removes_temporary_file(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import api.main as api
    monkeypatch.setenv("AWS_ENABLED", "false")
    monkeypatch.setattr(api, "UPLOAD_DIR", tmp_path)
    response = TestClient(api.app).post("/datasets/inspect", files={
        "file": ("invalid.xlsx", b"PK\x03\x04invalid workbook", "application/octet-stream")})
    assert response.status_code == 422
    assert not list(tmp_path.iterdir())
