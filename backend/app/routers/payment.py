from hashlib import sha256
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import Principal, get_principal, require_roles
from app.core.config import get_settings
from app.database.connection import get_db
from app.models.payment import Payment
from app.schemas.payment import (
    PaymentClientConfiguration,
    PaymentCreate,
    PaymentListResponse,
    PaymentResponse,
)
from app.services import customer_service, order_service, payment_service, webhook_service

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.get("/configuration", response_model=PaymentClientConfiguration)
def payment_configuration() -> PaymentClientConfiguration:
    settings = get_settings()
    return PaymentClientConfiguration(
        provider=cast(Literal["simulator", "stripe"], settings.payment_provider),
        publishable_key=settings.stripe_publishable_key,
        currency=settings.payment_currency,
    )


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_payment_endpoint(
    data: PaymentCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=1, max_length=255
    ),
    db: Session = Depends(get_db),
) -> PaymentResponse:
    key = idempotency_key.strip()
    if not key:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Idempotency-Key must not be blank",
        )
    customer_id = None
    if not principal.has_any_role({"operator", "admin"}):
        customer_id = customer_service.get_or_create_customer(db, principal).id
    order_service.get_order(db, data.order_id, customer_id)
    fingerprint = sha256(
        f"{principal.subject}:payment:{data.order_id}".encode()
    ).hexdigest()
    return payment_service.create_payment(
        db,
        data.order_id,
        key,
        principal_subject=principal.subject,
        request_fingerprint=fingerprint,
    )


@router.get("", response_model=PaymentListResponse)
def list_payments(
    principal: Annotated[Principal, Depends(get_principal)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    requires_review: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PaymentListResponse:
    filters = []
    if not principal.has_any_role({"operator", "admin"}):
        filters.append(Payment.principal_subject == principal.subject)
    if requires_review is not None:
        filters.append(Payment.requires_review.is_(requires_review))
    total = db.scalar(select(func.count()).select_from(Payment).where(*filters)) or 0
    payments = db.scalars(
        select(Payment)
        .where(*filters)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return PaymentListResponse(
        items=cast(list[PaymentResponse], list(payments)),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/reconcile", status_code=status.HTTP_202_ACCEPTED)
def reconcile_due_payments(
    principal: Annotated[
        Principal, Depends(require_roles("operator", "admin"))
    ],
    db: Session = Depends(get_db),
) -> dict[str, int]:
    return {"attempted": payment_service.reconcile_pending_payments(db)}


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias="Stripe-Signature"),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    processed = webhook_service.process_stripe_webhook(
        db, await request.body(), stripe_signature
    )
    return {"processed": processed}
