from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ShipmentCreate(BaseModel):
    order_id: int = Field(gt=0)
    allocation_ids: list[int] = Field(min_length=1)
    carrier: str | None = Field(default=None, max_length=100)
    tracking_number: str | None = Field(default=None, max_length=200)


class ShipmentUpdate(BaseModel):
    carrier: str | None = Field(default=None, max_length=100)
    tracking_number: str | None = Field(default=None, max_length=200)


class ShipmentItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    allocation_id: int
    quantity: int


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    warehouse_id: int
    status: str
    carrier: str | None
    tracking_number: str | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    items: list[ShipmentItemResponse]
