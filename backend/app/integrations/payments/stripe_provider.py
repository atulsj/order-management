from decimal import ROUND_HALF_UP, Decimal

import stripe

from app.core.config import Settings
from app.integrations.payments.types import ProviderResult, ProviderStatus


class StripePaymentProvider:
    def __init__(self, settings: Settings) -> None:
        if settings.stripe_secret_key is None:
            raise RuntimeError("STRIPE_SECRET_KEY is required for the Stripe provider")
        self._client = stripe.StripeClient(settings.stripe_secret_key.get_secret_value())

    def create_payment(
        self,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
        order_id: int,
    ) -> ProviderResult:
        intent = self._client.v1.payment_intents.create(
            {
                "amount": _minor_units(amount),
                "currency": currency.lower(),
                "automatic_payment_methods": {"enabled": True},
                "metadata": {
                    "order_id": str(order_id),
                    "oms_provider_key": idempotency_key,
                },
            },
            options={"idempotency_key": idempotency_key},
        )
        return ProviderResult(
            _stripe_status(intent.status),
            intent.id,
            client_secret=intent.client_secret,
        )

    def get_payment(self, provider_reference: str, idempotency_key: str) -> ProviderResult:
        if provider_reference:
            intent = self._client.v1.payment_intents.retrieve(provider_reference)
        else:
            matches = self._client.v1.payment_intents.search(
                {
                    "query": (
                        f"metadata['oms_provider_key']:'{idempotency_key}'"
                    ),
                    "limit": 1,
                }
            )
            if not matches.data:
                return ProviderResult(
                    ProviderStatus.UNKNOWN,
                    message="Stripe PaymentIntent was not found",
                )
            intent = matches.data[0]
        return ProviderResult(_stripe_status(intent.status), intent.id)

    def refund(
        self,
        provider_reference: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> ProviderResult:
        refund = self._client.v1.refunds.create(
            {
                "payment_intent": provider_reference,
                "amount": _minor_units(amount),
                "metadata": {"oms_provider_key": idempotency_key},
            },
            options={"idempotency_key": idempotency_key},
        )
        status = (
            ProviderStatus.SUCCEEDED
            if refund.status == "succeeded"
            else ProviderStatus.PROCESSING
        )
        if refund.status in {"failed", "canceled"}:
            status = ProviderStatus.FAILED
        return ProviderResult(status, refund.id)

    def get_refund(
        self, provider_reference: str, idempotency_key: str
    ) -> ProviderResult:
        refund = self._client.v1.refunds.retrieve(provider_reference)
        status = ProviderStatus.PROCESSING
        if refund.status == "succeeded":
            status = ProviderStatus.SUCCEEDED
        elif refund.status in {"failed", "canceled"}:
            status = ProviderStatus.FAILED
        return ProviderResult(status, refund.id)


def _minor_units(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _stripe_status(value: str) -> ProviderStatus:
    if value == "succeeded":
        return ProviderStatus.SUCCEEDED
    if value in {"canceled", "requires_payment_method"}:
        return ProviderStatus.FAILED
    if value in {
        "processing",
        "requires_action",
        "requires_confirmation",
        "requires_capture",
    }:
        return ProviderStatus.PROCESSING
    return ProviderStatus.UNKNOWN
