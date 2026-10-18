from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.schemas.payment import PaymentCreate, PaymentResponse
from app.services.payment_service import create_payment

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_payment_endpoint(
    data: PaymentCreate,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
    ),
    db: Session = Depends(get_db),
) -> PaymentResponse:
    idempotency_key = idempotency_key.strip()

    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key must not be blank",
        )

    try:
        return create_payment(
            db,
            data.order_id,
            idempotency_key,
        )
    except Exception:
        logger.exception("Payment creation failed")
        raise