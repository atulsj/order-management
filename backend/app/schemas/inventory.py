from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field


class InventoryCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity_on_hand: int = Field(ge=0)


class InventoryReceive(BaseModel):
    quantity: int = Field(gt=0)


class InventoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    quantity_on_hand: int
    quantity_reserved: int
    updated_at: datetime

    @computed_field
    @property
    def quantity_available(self) -> int:
        return self.quantity_on_hand - self.quantity_reserved