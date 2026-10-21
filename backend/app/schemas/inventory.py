from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field


class InventoryCreate(BaseModel):
    product_id: int = Field(gt=0)
    warehouse_id: int = Field(default=1, gt=0)
    quantity_on_hand: int = Field(ge=0)


class InventoryReceive(BaseModel):
    quantity: int = Field(gt=0)


class InventoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    warehouse_id: int
    quantity_on_hand: int
    quantity_reserved: int
    updated_at: datetime

    @computed_field
    @property
    def quantity_available(self) -> int:
        return self.quantity_on_hand - self.quantity_reserved


class InventoryAdjust(BaseModel):
    quantity_delta: int
    reason: str = Field(min_length=3, max_length=500)


class StockMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    inventory_id: int
    movement_type: str
    quantity_delta: int
    reason: str
    actor_subject: str | None
    reference_type: str | None
    reference_id: str | None
    created_at: datetime