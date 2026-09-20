"""Bounded execution service for natural-language AML investigations."""
from __future__ import annotations

from functools import lru_cache
from threading import BoundedSemaphore
from typing import Protocol

from agent.models import AgentResponse, QueryRequest


class QueryExecutionError(RuntimeError):
    """Base query service failure with no internal implementation detail."""


class QueryValidationError(QueryExecutionError):
    pass


class QueryCapacityError(QueryExecutionError):
    retry_after_seconds = 2


class QueryExecutor(Protocol):
    def run(
        self,
        query: str,
        dataset_id: str | None = None,
    ) -> AgentResponse: ...


class InvestigationSink(Protocol):
    def persist(self, response: AgentResponse) -> AgentResponse: ...


class RuntimeQueryExecutor:
    """Late-bound adapter to the dynamic agent runtime delivered in Phase 5."""

    def run(
        self,
        query: str,
        dataset_id: str | None = None,
    ) -> AgentResponse:
        from agent.runner import AgentRunner

        return AgentRunner().run(query, dataset_id=dataset_id)


class OptionalInvestigationSink:
    """Persist when the workflow store is installed; otherwise remain read-only."""

    def persist(self, response: AgentResponse) -> AgentResponse:
        try:
            from tools.workflow_store import persist_investigation
        except ModuleNotFoundError as exc:
            if exc.name != "tools.workflow_store":
                raise
            return response
        return persist_investigation(response)


class QueryService:
    """Validate, capacity-bound, execute, and validate agent responses."""

    def __init__(
        self,
        executor: QueryExecutor,
        sink: InvestigationSink | None = None,
        *,
        max_concurrent: int = 4,
    ):
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        self._executor = executor
        self._sink = sink
        self._capacity = BoundedSemaphore(max_concurrent)

    def run(self, request: QueryRequest) -> AgentResponse:
        if not self._capacity.acquire(blocking=False):
            raise QueryCapacityError("Agent capacity is temporarily exhausted")
        try:
            try:
                raw = self._executor.run(
                    request.query,
                    dataset_id=request.dataset_id,
                )
                response = AgentResponse.model_validate(raw)
                if self._sink is not None:
                    response = AgentResponse.model_validate(
                        self._sink.persist(response)
                    )
                return response
            except ValueError as exc:
                raise QueryValidationError(
                    "The query could not be executed for the selected evidence."
                ) from exc
        finally:
            self._capacity.release()


@lru_cache(maxsize=1)
def get_query_service() -> QueryService:
    return QueryService(
        RuntimeQueryExecutor(),
        OptionalInvestigationSink(),
    )
