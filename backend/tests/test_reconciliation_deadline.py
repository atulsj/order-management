from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import Payment
from app.services.payment_service import _mark_for_review


def test_expired_reconciliation_deadline_escalates_without_rescheduling():
    payment = Payment(
        order_id=1,
        amount=Decimal("10.00"),
        idempotency_key="deadline-client",
        provider_idempotency_key="deadline-provider",
        status="PENDING",
        reconciliation_deadline_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    _mark_for_review(payment, "Provider remains unavailable")

    assert payment.requires_review is True
    assert payment.next_reconciliation_at is None
    assert payment.review_reason is not None
    assert payment.review_reason.startswith("Reconciliation deadline exceeded")
