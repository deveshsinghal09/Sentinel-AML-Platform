"""Serialized Lambda workspace: S3 is durable; /tmp is a disposable cache."""
from contextlib import contextmanager
from pathlib import Path
import time
import uuid

from api.services.aws import settings
from api.services.aws.logging import event
from api.services.aws.s3_service import S3Service

SNAPSHOT_KEY = "state/workspace.duckdb"
LOCK_KEY = "__sentinel_workspace_lock__"


class WorkspaceBusy(RuntimeError):
    """Another invocation currently owns the single DuckDB workspace."""


@contextmanager
def workspace_lock(context=None, request_id=None, wait_seconds=5):
    """Serialize Lambda writers with an expiring conditional DynamoDB lock.

    New AWS accounts can have a concurrency quota of ten and reject Lambda
    reserved concurrency. This lock enforces the same single-writer invariant
    without relying on that account-level setting.
    """
    if not settings.enabled():
        yield
        return
    from botocore.exceptions import ClientError
    from api.services.aws.dynamodb_service import InvestigationRepository

    table = InvestigationRepository().table
    token = request_id or str(uuid.uuid4())
    deadline = time.monotonic() + wait_seconds
    while True:
        now = int(time.time())
        remaining = 900
        get_remaining = getattr(context, "get_remaining_time_in_millis", None)
        if callable(get_remaining):
            remaining = max(1, int(get_remaining() / 1000))
        expires_at = now + min(900, remaining + 30)
        try:
            table.put_item(
                Item={"investigation_id": LOCK_KEY, "kind": "runtime_lock",
                      "lock_token": token, "lock_expires_at": expires_at},
                ConditionExpression=("attribute_not_exists(investigation_id) "
                                     "OR lock_expires_at < :now"),
                ExpressionAttributeValues={":now": now},
            )
            break
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            if time.monotonic() >= deadline:
                event("workspace_lock_busy", request_id=request_id)
                raise WorkspaceBusy("AWS workspace is busy; retry shortly") from exc
            time.sleep(0.25)
    event("workspace_lock_acquired", request_id=request_id)
    try:
        yield
    finally:
        try:
            table.delete_item(
                Key={"investigation_id": LOCK_KEY},
                ConditionExpression="lock_token = :token",
                ExpressionAttributeValues={":token": token},
            )
            event("workspace_lock_released", request_id=request_id)
        except ClientError as exc:
            # A stale owner must never delete a newer invocation's lock.
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                event("workspace_lock_release_failed", request_id=request_id,
                      error_type=type(exc).__name__)


def restore():
    from config import DB_PATH
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Never reuse uncommitted warm-container state after an interrupted request.
    DB_PATH.unlink(missing_ok=True)
    Path(str(DB_PATH) + ".wal").unlink(missing_ok=True)
    s3 = S3Service()
    if s3.file_exists(SNAPSHOT_KEY):
        temporary = DB_PATH.with_suffix(".download")
        try:
            s3.download_file(SNAPSHOT_KEY, temporary)
            temporary.replace(DB_PATH)
        finally:
            temporary.unlink(missing_ok=True)
    from tools.ml_engine import clear_model_cache
    from tools.statistical import get_saml_iqr_bounds
    clear_model_cache()
    get_saml_iqr_bounds.cache_clear()


def checkpoint():
    from config import DB_PATH
    if DB_PATH.exists():
        # All application DB connections must be closed before this boundary.
        import duckdb
        connection = duckdb.connect(str(DB_PATH))
        try:
            connection.execute("CHECKPOINT")
        finally:
            connection.close()
        S3Service().upload_file(DB_PATH, SNAPSHOT_KEY)
        event("workspace_checkpoint_completed")


def sync_investigations():
    """Repair writes interrupted between the DuckDB commit and DynamoDB write."""
    from tools.workflow_store import _list_local_investigations, _get_local_investigation
    from api.services.aws.dynamodb_service import InvestigationRepository
    from api.services.aws.investigations import save, sync_workflow
    from api.services.aws.completion import complete
    repository = InvestigationRepository()
    for summary in _list_local_investigations(limit=10000):
        existing = repository.get_investigation(summary.investigation_id)
        if existing is None:
            save(_get_local_investigation(summary.investigation_id))
        elif any(existing.get(key) != getattr(summary, key)
                 for key in ("status", "disposition", "updated_at")):
            sync_workflow(summary)
        if existing is None or not existing.get("report_s3_key") or existing.get("notification_status") == "pending":
            try:
                complete(_get_local_investigation(summary.investigation_id).response)
            except Exception as exc:
                event("investigation_artifact_failed", investigation_id=summary.investigation_id,
                      error_type=type(exc).__name__)
