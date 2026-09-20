"""Role-neutral review workflow service with controlled state transitions."""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from api.repositories.workflow_repository import WorkflowRepository


class WorkflowNotFound(LookupError):
    pass


class WorkflowUnavailable(RuntimeError):
    pass


class WorkflowStore(Protocol):
    def list_alerts(self, **kwargs) -> tuple[list[dict[str, Any]], int]: ...
    def queue_summary(self) -> dict[str, int]: ...
    def assign(self, alert_id: str, analyst: str, actor: str) -> dict[str, Any]: ...
    def disposition(
        self, alert_id: str, disposition: str, actor: str
    ) -> dict[str, Any]: ...
    def append_note(self, alert_id: str, note: str, actor: str) -> dict[str, Any]: ...
    def list_audit(self, **kwargs) -> tuple[list[dict[str, Any]], int]: ...


class WorkflowService:
    def __init__(self, store: WorkflowStore):
        self._store = store

    def list_alerts(self, **kwargs) -> tuple[list[dict[str, Any]], int]:
        return self._call(self._store.list_alerts, **kwargs)

    def summary(self) -> dict[str, int]:
        return self._call(self._store.queue_summary)

    def assign(self, alert_id: str, analyst: str, actor: str) -> dict[str, Any]:
        return self._call(self._store.assign, alert_id, analyst, actor)

    def disposition(
        self,
        alert_id: str,
        disposition: str,
        actor: str,
    ) -> dict[str, Any]:
        return self._call(self._store.disposition, alert_id, disposition, actor)

    def append_note(self, alert_id: str, note: str, actor: str) -> dict[str, Any]:
        return self._call(self._store.append_note, alert_id, note, actor)

    def audit(self, **kwargs) -> tuple[list[dict[str, Any]], int]:
        return self._call(self._store.list_audit, **kwargs)

    @staticmethod
    def _call(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except KeyError as exc:
            raise WorkflowNotFound("Alert not found") from exc
        except WorkflowNotFound:
            raise
        except Exception as exc:
            raise WorkflowUnavailable("Workflow store unavailable") from exc


@lru_cache(maxsize=1)
def get_workflow_service() -> WorkflowService:
    return WorkflowService(WorkflowRepository())
