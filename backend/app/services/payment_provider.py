
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from uuid import uuid4
import os


# Local development simulator only.
# This database is separate from the OMS PostgreSQL database.
DB_PATH = Path(__file__).resolve().parents[2] / "test_provider.sqlite3"


class ProviderPaymentStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PROCESSING = "PROCESSING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PaymentResult:
    status: ProviderPaymentStatus
    provider_reference: str | None = None
    message: str | None = None


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_test_provider() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_transactions (
                idempotency_key TEXT PRIMARY KEY,
                provider_reference TEXT NOT NULL UNIQUE,
                amount TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def process_test_payment(
    amount: Decimal,
    idempotency_key: str,
) -> PaymentResult:
    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero")

    if not idempotency_key.strip():
        raise ValueError("Idempotency key must not be blank")

    initialize_test_provider()

    with _connect() as connection:
        existing = connection.execute(
            """
            SELECT amount, provider_reference, status
            FROM provider_transactions
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()

        if existing is not None:
            if Decimal(existing["amount"]) != amount:
                raise ValueError(
                    "Idempotency key reused with a different amount"
                )

            return PaymentResult(
                status=ProviderPaymentStatus(existing["status"]),
                provider_reference=existing["provider_reference"],
                message="Existing simulated transaction",
            )

        # Choose the outcome configured for this test run.
        simulated_status = _configured_test_status()

        provider_reference = f"test_{uuid4().hex}"

        connection.execute(
            """
            INSERT INTO provider_transactions (
                idempotency_key,
                provider_reference,
                amount,
                status
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                idempotency_key,
                provider_reference,
                str(amount),
                simulated_status.value,
            ),
        )

        return PaymentResult(
            status=simulated_status,
            provider_reference=provider_reference,
            message=f"Simulated payment {simulated_status.value.lower()}",
        )

def get_test_payment_status(
    idempotency_key: str,
) -> PaymentResult:
    initialize_test_provider()

    with _connect() as connection:
        existing = connection.execute(
            """
            SELECT provider_reference, status
            FROM provider_transactions
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()

    if existing is None:
        return PaymentResult(
            status=ProviderPaymentStatus.UNKNOWN,
            message="No transaction found for this key",
        )

    return PaymentResult(
        status=ProviderPaymentStatus(existing["status"]),
        provider_reference=existing["provider_reference"],
        message="Retrieved simulated transaction status",
    )

def _configured_test_status() -> ProviderPaymentStatus:
    value = os.getenv(
        "TEST_PROVIDER_OUTCOME",
        "SUCCEEDED",
    ).strip().upper()

    try:
        return ProviderPaymentStatus(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid TEST_PROVIDER_OUTCOME: {value}"
        ) from exc