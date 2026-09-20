"""Authenticated, bounded customer and transaction evidence APIs."""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from agent.models import CustomerDetail, CustomerSummary, TransactionRecord
from api.security.dependencies import require_authenticated_session
from api.services.auth_service import AuthSession
from api.services.evidence_service import (
    EvidenceNotFound,
    EvidenceService,
    EvidenceUnavailable,
    get_evidence_service,
)


logger = logging.getLogger(__name__)

router = APIRouter(tags=["evidence"])
_ACCOUNT_ID = re.compile(r"^[^\x00-\x1f/\\]{1,120}$")


class CustomerPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CustomerSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class TransactionPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TransactionRecord]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class PaymentFormatList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[str]


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _service_unavailable(message: str, exc: Exception) -> HTTPException:
    logger.exception(message)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Evidence is temporarily unavailable.",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get(
    "/customers",
    response_model=CustomerPage,
    summary="List customer risk and activity summaries",
)
def list_customer_evidence(
    response: Response,
    search: str | None = Query(default=None, max_length=120),
    risk_label: Literal["unscored", "low", "medium", "high"] | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: AuthSession = Depends(require_authenticated_session),
    service: EvidenceService = Depends(get_evidence_service),
) -> CustomerPage:
    _no_store(response)
    try:
        items, total = service.list_customers(
            search=search.strip() if search else None,
            risk_label=risk_label,
            limit=limit,
            offset=offset,
        )
        return CustomerPage(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )
    except EvidenceUnavailable as exc:
        raise _service_unavailable(
            "Customer evidence lookup failed",
            exc,
        ) from exc


@router.get(
    "/customers/{account_id}",
    response_model=CustomerDetail,
    summary="Get consolidated evidence for one customer",
)
def customer_evidence_detail(
    response: Response,
    account_id: str = Path(
        min_length=1,
        max_length=120,
        pattern=_ACCOUNT_ID.pattern,
    ),
    _: AuthSession = Depends(require_authenticated_session),
    service: EvidenceService = Depends(get_evidence_service),
) -> CustomerDetail:
    _no_store(response)
    try:
        return service.get_customer(account_id)
    except EvidenceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found.",
            headers={"Cache-Control": "private, no-store"},
        ) from exc
    except EvidenceUnavailable as exc:
        raise _service_unavailable(
            "Customer evidence detail failed",
            exc,
        ) from exc


@router.get(
    "/transactions/payment-formats",
    response_model=PaymentFormatList,
    summary="List payment formats in the active evidence set",
)
def transaction_payment_formats(
    response: Response,
    _: AuthSession = Depends(require_authenticated_session),
    service: EvidenceService = Depends(get_evidence_service),
) -> PaymentFormatList:
    _no_store(response)
    try:
        return PaymentFormatList(items=service.payment_formats())
    except EvidenceUnavailable as exc:
        raise _service_unavailable(
            "Payment-format lookup failed",
            exc,
        ) from exc


@router.get(
    "/transactions",
    response_model=TransactionPage,
    summary="Browse a filtered transaction evidence page",
)
def list_transaction_evidence(
    response: Response,
    account_id: str | None = Query(default=None, max_length=120),
    direction: Literal["both", "inbound", "outbound"] = "both",
    payment_format: str | None = Query(default=None, max_length=120),
    min_amount: float | None = Query(default=None, ge=0),
    max_amount: float | None = Query(default=None, ge=0),
    date_from: date | None = None,
    date_to: date | None = None,
    laundering_only: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: AuthSession = Depends(require_authenticated_session),
    service: EvidenceService = Depends(get_evidence_service),
) -> TransactionPage:
    _no_store(response)
    if direction != "both" and not account_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Direction requires an account_id filter.",
            headers={"Cache-Control": "private, no-store"},
        )
    if (
        min_amount is not None
        and max_amount is not None
        and min_amount > max_amount
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="min_amount cannot exceed max_amount.",
            headers={"Cache-Control": "private, no-store"},
        )
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from cannot be after date_to.",
            headers={"Cache-Control": "private, no-store"},
        )
    if account_id and not _ACCOUNT_ID.fullmatch(account_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="account_id contains unsupported characters.",
            headers={"Cache-Control": "private, no-store"},
        )

    try:
        items, total = service.list_transactions(
            account_id=account_id,
            direction=direction,
            payment_format=payment_format.strip() if payment_format else None,
            min_amount=min_amount,
            max_amount=max_amount,
            date_from=date_from,
            date_to=date_to,
            laundering_only=laundering_only,
            limit=limit,
            offset=offset,
        )
        return TransactionPage(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )
    except EvidenceUnavailable as exc:
        raise _service_unavailable(
            "Transaction evidence lookup failed",
            exc,
        ) from exc
