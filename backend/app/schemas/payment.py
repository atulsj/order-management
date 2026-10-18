
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
