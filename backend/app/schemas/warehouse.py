from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9_-]+$")
    name: str = Field(min_length=2, max_length=200)
    priority: int = Field(default=100, ge=1, le=10000)


class WarehouseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    priority: int | None = Field(default=None, ge=1, le=10000)
    is_active: bool | None = None


class WarehouseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
