from functools import lru_cache

from app.core.config import get_settings
from app.database.connection import SessionLocal
from app.integrations.payments.simulator import SimulatorPaymentProvider
from app.integrations.payments.stripe_provider import StripePaymentProvider
from app.integrations.payments.types import PaymentProvider


@lru_cache
def get_payment_provider() -> PaymentProvider:
    settings = get_settings()
    if settings.payment_provider == "stripe":
        return StripePaymentProvider(settings)
    return SimulatorPaymentProvider(SessionLocal)
