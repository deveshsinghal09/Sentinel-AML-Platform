"""Private S3 object storage with explicit errors and temporary downloads."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from api.services.aws import settings
from api.services.aws.logging import event


class S3Service:
    def __init__(self, bucket=None, client=None):
        self.bucket = bucket or settings.required("AWS_S3_BUCKET")
        self.client = client or settings.client("s3")

    def upload_file(self, path, key, metadata=None):
        event("dataset_upload_started" if key.startswith("datasets/") else "s3_upload_started")
        try:
            self.client.upload_file(str(path), self.bucket, key,
                                    ExtraArgs={"Metadata": metadata or {}})
        except Exception as exc:
            event("s3_upload_failed", error_type=type(exc).__name__)
            raise
        event("dataset_upload_completed" if key.startswith("datasets/") else "s3_upload_completed")
        return key

    def put_bytes(self, content: bytes, key: str, content_type="application/octet-stream"):
        event("s3_upload_started")
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=content_type)
        except Exception as exc:
            event("s3_upload_failed", error_type=type(exc).__name__)
            raise
        event("s3_upload_completed")
        return key

    def download_file(self, key, path):
        try:
            self.client.download_file(self.bucket, key, str(path))
        except Exception as exc:
            event("s3_download_failed", error_type=type(exc).__name__)
            raise
        return Path(path)

    @contextmanager
    def temporary_file(self, key):
        with TemporaryDirectory(prefix="sentinel-") as directory:
            path = Path(directory) / ("object" + Path(key).suffix.lower())
            yield self.download_file(key, path)

    def generate_presigned_url(self, key, expires_in=300):
        return self.client.generate_presigned_url("get_object", Params={
            "Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in)

    def file_exists(self, key):
        from botocore.exceptions import ClientError
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def delete_file(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)
