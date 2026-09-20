"""Durable object-location metadata alongside the existing dataset registry."""
import json
from datetime import datetime, timezone

from api.services.aws.s3_service import S3Service


def store_metadata(s3, dataset_id, key, filename, dataset_type, fingerprint):
    metadata_key = f"state/datasets/{dataset_id}.json"
    # Keep the original filename/timestamp on repeated identical uploads.
    if not s3.file_exists(metadata_key):
        payload = {"dataset_id": dataset_id, "filename": filename, "s3_key": key,
                   "dataset_type": dataset_type, "fingerprint": fingerprint,
                   "uploaded_at": datetime.now(timezone.utc).isoformat()}
        s3.put_bytes(json.dumps(payload).encode(), metadata_key, "application/json")
    return metadata_key


def upload_dataset(path, dataset_id, filename, dataset_type, fingerprint):
    s3 = S3Service()
    key = f"datasets/{dataset_id}/transactions{path.suffix.lower()}"
    s3.upload_file(path, key, {"dataset-id": dataset_id, "dataset-type": dataset_type})
    store_metadata(s3, dataset_id, key, filename, dataset_type, fingerprint)
    return key
