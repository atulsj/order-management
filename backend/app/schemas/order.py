from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OrderItemCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(min_length=1)


class OrderItemResponse(BaseModel):  # type: ignore[reportUnknownBaseType]
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    quantity: int
    unit_price: Decimal


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: Literal[
        "PENDING_PAYMENT",
        "CONFIRMED",
        "CANCELLED",
    ]
    total_amount: Decimal
    created_at: datetime
    items: list[OrderItemResponse]

class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    total: int
    limit: int
    offset: int