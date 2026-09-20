"""Single serialized container handles HTTP and S3 events using shared modules."""
import os
import json


def _http(event, context, lifespan="auto"):
    from mangum import Mangum
    from api.main import app
    return Mangum(app, lifespan=lifespan)(event, context)


def handler(event, context):
    # Set writable Lambda paths before importing config or analytical modules.
    os.environ.setdefault("AWS_ENABLED", "true")
    os.environ.setdefault("DATA_DIR", "/tmp/sentinel")
    os.environ.setdefault("DB_PATH", "/tmp/sentinel/aml.duckdb")
    os.environ.setdefault("UPLOAD_DIR", "/tmp/sentinel/uploads")
    from api.services.aws.logging import configure, event as log
    from api.services.aws.runtime import restore, checkpoint, sync_investigations, workspace_lock
    configure()
    request_id = getattr(context, "aws_request_id", None)
    is_http = "requestContext" in event
    log("lambda_started", request_id=request_id)
    try:
        # Liveness must remain usable even when a storage dependency is down.
        if is_http and event.get("rawPath") == "/health":
            return _http(event, context, lifespan="off")
        with workspace_lock(context, request_id=request_id):
            restore()
            try:
                if not is_http:
                    from aws.lambdas.s3_ingestion.handler import handler as ingest
                    return ingest(event, context)
                return _http(event, context)
            finally:
                checkpoint()
                sync_investigations()
    except Exception as exc:
        log("lambda_failed", request_id=request_id, error_type=type(exc).__name__)
        if is_http:
            return {"statusCode": 503, "headers": {"content-type": "application/json"},
                    "body": json.dumps({"detail": "AWS storage or analysis is unavailable. Retry shortly.",
                                        "request_id": request_id})}
        raise
