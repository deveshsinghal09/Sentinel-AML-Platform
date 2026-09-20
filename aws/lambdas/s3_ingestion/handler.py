"""Validate S3 notifications, deduplicate, and run the existing AML pipeline."""
import hashlib
import json
import os
import re
from pathlib import Path
from time import perf_counter
from urllib.parse import unquote_plus
from zipfile import BadZipFile

from api.services.aws.logging import event as log
from api.services.aws.s3_service import S3Service


def parse_record(record, expected_bucket):
    if record.get("eventSource") != "aws:s3" or not record.get("eventName", "").startswith("ObjectCreated:"):
        return None
    bucket = record.get("s3", {}).get("bucket", {}).get("name")
    obj = record.get("s3", {}).get("object", {})
    key = unquote_plus(obj.get("key", ""))
    if bucket != expected_bucket:
        raise ValueError("Unexpected S3 bucket")
    match = re.fullmatch(r"datasets/([A-Za-z0-9][A-Za-z0-9_.-]{0,79})/([^/]+\.(?:csv|xlsx))", key, re.IGNORECASE)
    if not match:
        return None
    etag = obj.get("eTag", "").strip('"')
    if not etag:
        raise ValueError("S3 event is missing eTag")
    return {"bucket": bucket, "key": key, "dataset_id": match[1], "etag": etag}


def process_object(item, s3):
    from agent.runner import AgentRunner
    from tools.dataset_store import register_uploaded_dataset, get_dataset
    from tools.workflow_store import persist_investigation, _get_local_investigation
    from api.services.aws.investigations import event_investigation_id
    from api.services.aws.completion import complete
    from api.services.aws.runtime import checkpoint
    from api.services.aws.datasets import store_metadata

    identity = hashlib.sha256(f"{item['bucket']}/{item['key']}:{item['etag']}".encode()).hexdigest()
    receipt_key = f"state/ingestion/{identity}.json"
    if s3.file_exists(receipt_key):
        with s3.temporary_file(receipt_key) as receipt:
            previous = json.loads(receipt.read_text())
        if previous["status"] in {"completed", "invalid"}:
            return {**previous, "duplicate": True}
    head = s3.client.head_object(Bucket=item["bucket"], Key=item["key"])
    if head["ETag"].strip('"') != item["etag"]:
        return {"status": "ignored", "reason": "superseded_object"}
    if head["ContentLength"] > int(os.getenv("AWS_MAX_DATASET_BYTES", "52428800")):
        result = {"status": "invalid", "reason": "Dataset exceeds AWS_MAX_DATASET_BYTES"}
        s3.put_bytes(json.dumps(result).encode(), receipt_key, "application/json")
        return result
    started = perf_counter()
    log("dataset_ingestion_started", dataset_id=item["dataset_id"])
    try:
        with s3.temporary_file(item["key"]) as path:
            fingerprint = hashlib.md5(path.read_bytes()).hexdigest()
            dataset_id = f"ds_{fingerprint[:12]}"
            dataset_type = head.get("Metadata", {}).get("dataset-type", "primary")
            existing = get_dataset(dataset_id)
            if existing is None:
                try:
                    register_uploaded_dataset(path=path, display_name=dataset_id,
                        dataset_type=dataset_type, md5_fingerprint=fingerprint,
                        file_size_bytes=path.stat().st_size, source_file=Path(item["key"]).name)
                except (ValueError, BadZipFile):
                    result = {"status": "invalid", "dataset_id": dataset_id,
                              "reason": "Dataset failed existing schema/row validation"}
                    s3.put_bytes(json.dumps(result).encode(), receipt_key, "application/json")
                    log("dataset_ingestion_failed", dataset_id=dataset_id, status="invalid")
                    return result
            elif existing.md5_fingerprint != fingerprint or existing.dataset_type != dataset_type:
                raise ValueError("Conflicting dataset identity or type")
        store_metadata(s3, dataset_id, item["key"], Path(item["key"]).name, dataset_type, fingerprint)
        checkpoint()  # retain ingestion even if analysis fails or times out
        result = {"status": "completed", "dataset_id": dataset_id}
        if dataset_type == "primary":
            investigation_id = "INV-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:24].upper()
            token = event_investigation_id.set(investigation_id)
            try:
                previous = _get_local_investigation(investigation_id)
                log("investigation_started", dataset_id=dataset_id, investigation_id=investigation_id)
                response = previous.response if previous else AgentRunner(use_llm=False).run(
                    "Investigate suspicious transactions for money laundering including structuring and networks",
                    dataset_id=dataset_id)
                response = persist_investigation(response)
                complete(response)  # retry report failures; SNS failure remains nonfatal
                result["investigation_id"] = response.investigation_id
            finally:
                event_investigation_id.reset(token)
        s3.put_bytes(json.dumps(result).encode(), receipt_key, "application/json")
        log("dataset_ingestion_completed", dataset_id=dataset_id,
            duration_ms=round((perf_counter() - started) * 1000))
        return result
    except Exception as exc:
        # Store diagnostic status, but raise so Lambda retries transient failures.
        log("dataset_ingestion_failed", dataset_id=item["dataset_id"], error_type=type(exc).__name__)
        s3.put_bytes(json.dumps({"status": "failed", "dataset_id": item["dataset_id"],
                                "error_type": type(exc).__name__}).encode(), receipt_key, "application/json")
        raise


def handler(event, context=None):
    records = event.get("Records")
    if not isinstance(records, list) or not records:
        return {"status": "ignored", "reason": "missing_records", "results": []}
    s3 = S3Service()
    results, failed = [], False
    for record in records:
        try:
            item = parse_record(record, s3.bucket)
            results.append(process_object(item, s3) if item else {"status": "ignored"})
        except Exception as exc:
            failed = True
            log("dataset_ingestion_failed", error_type=type(exc).__name__)
            results.append({"status": "failed", "error_type": type(exc).__name__})
    if failed:
        # Returning an error dictionary would acknowledge and lose the S3 event.
        raise RuntimeError(json.dumps({"status": "retry_required", "results": results}))
    return {"status": "ok", "results": results}
