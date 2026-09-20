"""Governed evidence service separating API contracts from persistence tools."""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from agent.models import CustomerDetail, CustomerSummary, TransactionRecord


class EvidenceServiceError(RuntimeError):
    """Base failure that intentionally omits persistence implementation detail."""


class EvidenceNotFound(EvidenceServiceError):
    pass


class EvidenceUnavailable(EvidenceServiceError):
    pass


class EvidenceBackend(Protocol):
    def list_customers(
        self,
        *,
        search: str | None,
        risk_label: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Any], int]: ...

    def get_customer(self, account_id: str) -> Any | None: ...

    def list_transactions(self, **filters: Any) -> tuple[list[Any], int]: ...

    def payment_formats(self) -> list[str]: ...


class RuntimeEvidenceBackend:
    """Late-bound bridge to the repository-backed browsing tools."""

    def list_customers(self, **filters: Any) -> tuple[list[Any], int]:
        from tools.customer_browser import list_customers

        return list_customers(**filters)

    def get_customer(self, account_id: str) -> Any | None:
        from tools.customer_browser import get_customer

        record = get_customer(account_id)
        if record is None:
            return None
        try:
            from tools.workflow_store import list_entity_alerts
        except ModuleNotFoundError as exc:
            if exc.name != "tools.workflow_store":
                raise
            return record
        return record.model_copy(
            update={"alerts": list_entity_alerts(account_id)}
        )

    def list_transactions(self, **filters: Any) -> tuple[list[Any], int]:
        from tools.transaction_browser import list_transactions

        return list_transactions(**filters)

    def payment_formats(self) -> list[str]:
        from tools.transaction_browser import payment_formats

        return payment_formats()


class EvidenceService:
    """Validate repository output before it crosses the API boundary."""

    def __init__(self, backend: EvidenceBackend):
        self._backend = backend

    @staticmethod
    def _page(
        records: list[Any],
        total: int,
        model: type[CustomerSummary] | type[TransactionRecord],
    ) -> tuple[list[Any], int]:
        items = [model.model_validate(record) for record in records]
        normalized_total = int(total)
        if normalized_total < len(items) or normalized_total < 0:
            raise EvidenceUnavailable("Evidence page total is inconsistent")
        return items, normalized_total

    def list_customers(
        self,
        *,
        search: str | None,
        risk_label: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[CustomerSummary], int]:
        try:
            records, total = self._backend.list_customers(
                search=search,
                risk_label=risk_label,
                limit=limit,
                offset=offset,
            )
            return self._page(records, total, CustomerSummary)
        except EvidenceServiceError:
            raise
        except Exception as exc:
            raise EvidenceUnavailable(
                "Customer evidence backend failed"
            ) from exc

    def get_customer(self, account_id: str) -> CustomerDetail:
        try:
            record = self._backend.get_customer(account_id)
            if record is None:
                raise EvidenceNotFound("Customer not found")
            return CustomerDetail.model_validate(record)
        except EvidenceServiceError:
            raise
        except Exception as exc:
            raise EvidenceUnavailable(
                "Customer evidence backend failed"
            ) from exc

    def list_transactions(
        self,
        **filters: Any,
    ) -> tuple[list[TransactionRecord], int]:
        try:
            records, total = self._backend.list_transactions(**filters)
            return self._page(records, total, TransactionRecord)
        except EvidenceServiceError:
            raise
        except Exception as exc:
            raise EvidenceUnavailable(
                "Transaction evidence backend failed"
            ) from exc

    def payment_formats(self) -> list[str]:
        try:
            formats = self._backend.payment_formats()
            normalized: dict[str, str] = {}
            for value in formats:
                item = str(value).strip()
                if item:
                    normalized.setdefault(item.casefold(), item)
            return sorted(normalized.values(), key=str.casefold)
        except Exception as exc:
            raise EvidenceUnavailable(
                "Payment-format backend failed"
            ) from exc


@lru_cache(maxsize=1)
def get_evidence_service() -> EvidenceService:
    return EvidenceService(RuntimeEvidenceBackend())
