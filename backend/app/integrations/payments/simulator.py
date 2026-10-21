from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.integrations.payments.types import ProviderResult, ProviderStatus
from app.models.integration_event import SimulatorTransaction


class SimulatorPaymentProvider:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_payment(
        self,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
        order_id: int,
    ) -> ProviderResult:
        return self._process("PAYMENT", amount, currency, idempotency_key)

    def get_payment(self, provider_reference: str, idempotency_key: str) -> ProviderResult:
        with self._session_factory() as db:
            transaction = db.scalar(
                select(SimulatorTransaction).where(
                    SimulatorTransaction.idempotency_key == idempotency_key
                )
            )
            if transaction is None:
                return ProviderResult(ProviderStatus.UNKNOWN, message="Transaction not found")
            return ProviderResult(
                ProviderStatus(transaction.status),
                transaction.provider_reference,
                "Retrieved simulated transaction",
            )

    def refund(
        self,
        provider_reference: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> ProviderResult:
        return self._process("REFUND", amount, currency, idempotency_key)

    def get_refund(
        self, provider_reference: str, idempotency_key: str
    ) -> ProviderResult:
        return self.get_payment(provider_reference, idempotency_key)

    def _process(
        self, operation: str, amount: Decimal, currency: str, idempotency_key: str
    ) -> ProviderResult:
        if amount <= 0:
            raise ValueError("Amount must be greater than zero")
        with self._session_factory() as db:
            existing = db.scalar(
                select(SimulatorTransaction).where(
                    SimulatorTransaction.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                if existing.amount != amount or existing.operation != operation:
                    raise ValueError("Idempotency key reused with different input")
                return ProviderResult(
                    ProviderStatus(existing.status),
                    existing.provider_reference,
                    "Existing simulated transaction",
                )
            configured = get_settings().simulator_outcome.upper()
            outcome = ProviderStatus(configured)
            transaction = SimulatorTransaction(
                idempotency_key=idempotency_key,
                provider_reference=f"sim_{uuid4().hex}",
                operation=operation,
                amount=amount,
                currency=currency,
                status=outcome.value,
            )
            db.add(transaction)
            db.commit()
            return ProviderResult(
                outcome,
                transaction.provider_reference,
                f"Simulated {operation.lower()} {outcome.value.lower()}",
            )
