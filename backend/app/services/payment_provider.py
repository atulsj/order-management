from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.core.config import get_settings
from app.integrations.payments.factory import get_payment_provider
from app.integrations.payments.types import ProviderResult


class ProviderPaymentStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PROCESSING = "PROCESSING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PaymentResult:
    status: ProviderPaymentStatus
    provider_reference: str | None = None
    message: str | None = None
    client_secret: str | None = None


def process_test_payment(
    amount: Decimal,
    idempotency_key: str,
    order_id: int = 0,
    currency: str | None = None,
) -> PaymentResult:
    result = get_payment_provider().create_payment(
        amount,
        currency or get_settings().payment_currency,
        idempotency_key,
        order_id,
    )
    return _compat(result)


def get_test_payment_status(
    idempotency_key: str,
    provider_reference: str = "",
) -> PaymentResult:
    result = get_payment_provider().get_payment(provider_reference, idempotency_key)
    return _compat(result)


def _compat(result: ProviderResult) -> PaymentResult:
    return PaymentResult(
        status=ProviderPaymentStatus(result.status.value),
        provider_reference=result.provider_reference,
        message=result.message,
        client_secret=result.client_secret,
    )
