
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PaymentCreate(BaseModel):
    order_id: int


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    amount: Decimal
    status: Literal["PENDING", "SUCCEEDED", "FAILED", "REFUNDED"]
    provider_reference: str | None
    created_at: datetime
    attempt_number: int
    requires_review: bool
    review_reason: str | None
    next_reconciliation_at: datetime | None
    reconciliation_deadline_at: datetime | None
    client_secret: str | None = None


class PaymentListResponse(BaseModel):
    items: list[PaymentResponse]
    total: int
    limit: int
    offset: int


class PaymentClientConfiguration(BaseModel):
    provider: Literal["simulator", "stripe"]
    publishable_key: str | None
    currency: str


class RefundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    payment_id: int
    amount: Decimal
    status: str
    provider_reference: str | None
    review_reason: str | None
    created_at: datetime
