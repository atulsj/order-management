
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.integrations.payments.simulator import SimulatorPaymentProvider
from app.integrations.payments.types import ProviderStatus


def test_simulator_persists_idempotent_result(db_session, monkeypatch):
    factory = sessionmaker(
        bind=db_session.get_bind(),
        class_=Session,
        expire_on_commit=False,
    )
    provider = SimulatorPaymentProvider(factory)
    monkeypatch.setattr(get_settings(), "simulator_outcome", "FAILED")
    first = provider.create_payment(
        Decimal("100.00"), "USD", "simulator-idempotency", 1
    )
    monkeypatch.setattr(get_settings(), "simulator_outcome", "SUCCEEDED")
    repeated = provider.create_payment(
        Decimal("100.00"), "USD", "simulator-idempotency", 1
    )
    queried = provider.get_payment(
        first.provider_reference or "", "simulator-idempotency"
    )

    assert first.status == ProviderStatus.FAILED
    assert repeated == first
    assert queried.status == ProviderStatus.FAILED
