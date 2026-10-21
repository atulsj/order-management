from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AddressCreate(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    recipient_name: str = Field(min_length=1, max_length=200)
    line1: str = Field(min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=120)
    region: str = Field(min_length=1, max_length=120)
    postal_code: str = Field(min_length=1, max_length=32)
    country_code: str = Field(min_length=2, max_length=2)
    phone: str | None = Field(default=None, max_length=32)
    is_default: bool = False

    @field_validator("country_code")
    @classmethod
    def uppercase_country(cls, value: str) -> str:
        return value.upper()


class AddressResponse(AddressCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str | None
    display_name: str | None
    addresses: list[AddressResponse]
