from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class ProviderStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PROCESSING = "PROCESSING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProviderResult:
    status: ProviderStatus
    provider_reference: str | None = None
    message: str | None = None
    client_secret: str | None = None


class PaymentProvider(Protocol):
    def create_payment(
        self,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
        order_id: int,
    ) -> ProviderResult: ...

    def get_payment(self, provider_reference: str, idempotency_key: str) -> ProviderResult: ...

    def refund(
        self,
        provider_reference: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> ProviderResult: ...

    def get_refund(
        self, provider_reference: str, idempotency_key: str
    ) -> ProviderResult: ...
