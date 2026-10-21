from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.customer import AddressCreate


class OrderItemCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(min_length=1)
    address_id: int | None = Field(default=None, gt=0)
    shipping_address: AddressCreate | None = None


class OrderItemResponse(BaseModel):  # type: ignore[reportUnknownBaseType]
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    quantity: int
    unit_price: Decimal
    allocations: list["AllocationResponse"] = []


class AllocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    inventory_id: int
    quantity: int
    status: str


class OrderAddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipient_name: str
    line1: str
    line2: str | None
    city: str
    region: str
    postal_code: str
    country_code: str
    phone: str | None


class OrderEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    actor_subject: str | None
    data: dict
    created_at: datetime


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    currency: str
    total_amount: Decimal
    created_at: datetime
    items: list[OrderItemResponse]
    shipping_address: OrderAddressResponse | None = None
    events: list[OrderEventResponse] = []

class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    total: int
    limit: int
    offset: int