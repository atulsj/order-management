
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app.models import Inventory, Order, Payment, Product
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services import payment_service
from app.services.order_service import create_order
from app.services.payment_provider import (
    PaymentResult,
    ProviderPaymentStatus,
)

# ---------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------

def create_test_product_and_inventory(
    db_session, sku: str, price: str = "100.00"
):
    product = Product(
        sku=sku,
        name=f"Test product {sku}",
        price=Decimal(price),
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    inventory = Inventory(
        product_id=product.id,
        quantity_on_hand=10,
        quantity_reserved=0,
    )
    db_session.add(inventory)
    db_session.commit()

    return product


def create_test_order(db_session, product, quantity: int = 2):
    return create_order(
        db_session,
        OrderCreate(
            items=[
                OrderItemCreate(
                    product_id=product.id,
                    quantity=quantity,
                )
            ]
        ),
    )


def get_inventory(db_session, product_id: int) -> Inventory:
    inventory = db_session.scalar(
        select(Inventory).where(
            Inventory.product_id == product_id
        )
    )
    assert inventory is not None
    return inventory


# ---------------------------------------------------------------------
# Test 1: Failed payment preserves inventory
# ---------------------------------------------------------------------

def test_failed_payment_preserves_inventory(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-FAILED"
    )
    order = create_test_order(db_session, product)

    def fake_failed_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.FAILED,
            message="Payment declined",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_failed_payment,
    )

    payment = payment_service.create_payment(
        db_session, order.id, "test-failed-1"
    )

    assert payment.status == "FAILED"

    inventory = get_inventory(db_session, product.id)
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 2


# ---------------------------------------------------------------------
# Test 2: Successful payment confirms order and deducts inventory
# ---------------------------------------------------------------------

def test_successful_payment_confirms_order_and_deducts_inventory(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-SUCCESS"
    )
    order = create_test_order(db_session, product)

    def fake_successful_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.SUCCEEDED,
            provider_reference="provider-success-001",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_successful_payment,
    )

    payment = payment_service.create_payment(
        db_session, order.id, "test-success-1"
    )

    assert payment.status == "SUCCEEDED"

    saved_order = db_session.get(Order, order.id)
    assert saved_order is not None
    assert saved_order.status == "CONFIRMED"

    inventory = get_inventory(db_session, product.id)
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 2


# ---------------------------------------------------------------------
# Test 3: Repeating the same idempotency key does not charge twice
# ---------------------------------------------------------------------

def test_repeated_payment_key_does_not_deduct_inventory_twice(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-IDEMPOTENT"
    )
    order = create_test_order(db_session, product)
    provider_calls = []

    def fake_successful_payment(amount, idempotency_key):
        provider_calls.append(idempotency_key)
        return PaymentResult(
            status=ProviderPaymentStatus.SUCCEEDED,
            provider_reference="provider-idempotent-001",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_successful_payment,
    )

    first = payment_service.create_payment(
        db_session, order.id, "test-idempotent-1"
    )
    second = payment_service.create_payment(
        db_session, order.id, "test-idempotent-1"
    )

    assert first.id == second.id
    assert first.status == "SUCCEEDED"
    assert len(provider_calls) == 1

    inventory = get_inventory(db_session, product.id)
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 2


# ---------------------------------------------------------------------
# Test 4: An idempotency key cannot be reused for another order
# ---------------------------------------------------------------------

def test_idempotency_key_cannot_be_reused_for_another_order(
    db_session, monkeypatch
):
    product1 = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-ORDER-A"
    )
    product2 = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-ORDER-B"
    )

    order1 = create_test_order(db_session, product1)
    order2 = create_test_order(db_session, product2)

    def fake_successful_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.SUCCEEDED,
            provider_reference=f"provider-{idempotency_key}",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_successful_payment,
    )

    payment_service.create_payment(
        db_session, order1.id, "shared-idempotency-key"
    )

    with pytest.raises(HTTPException) as exc_info:
        payment_service.create_payment(
            db_session, order2.id, "shared-idempotency-key"
        )

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------
# Test 5: Processing payment requires reconciliation
# ---------------------------------------------------------------------

def test_processing_payment_requires_reconciliation(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-PROCESSING"
    )
    order = create_test_order(db_session, product)

    def fake_processing_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.PROCESSING,
            message="Still processing",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_processing_payment,
    )

    payment = payment_service.create_payment(
        db_session, order.id, "test-processing-1"
    )

    assert payment.status == "PENDING"
    assert payment.requires_review is True
    assert payment.next_reconciliation_at is not None

    saved_order = db_session.get(Order, order.id)
    assert saved_order is not None
    assert saved_order.status == "PENDING_PAYMENT"

    inventory = get_inventory(db_session, product.id)
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 2

    with pytest.raises(HTTPException) as exc_info:
        payment_service.create_payment(
            db_session, order.id, "test-processing-2"
        )

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------
# Test 6: Provider exception leaves payment pending for review
# ---------------------------------------------------------------------

def test_provider_timeout_keeps_payment_pending_for_review(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-TIMEOUT"
    )
    order = create_test_order(db_session, product)

    def fake_timeout(amount, idempotency_key):
        raise TimeoutError("Simulated provider timeout")

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_timeout,
    )

    with pytest.raises(HTTPException) as exc_info:
        payment_service.create_payment(
            db_session, order.id, "test-timeout-1"
        )

    assert exc_info.value.status_code == 502

    payment = db_session.scalar(
        select(Payment).where(
            Payment.idempotency_key == "test-timeout-1"
        )
    )
    assert payment is not None
    assert payment.status == "PENDING"
    assert payment.requires_review is True

    inventory = get_inventory(db_session, product.id)
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 2


# ---------------------------------------------------------------------
# Test 7: Unknown provider status requires reconciliation
# ---------------------------------------------------------------------

def test_unknown_provider_status_requires_reconciliation(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-UNKNOWN"
    )
    order = create_test_order(db_session, product)

    def fake_unknown_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.UNKNOWN,
            message="Unknown provider outcome",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_unknown_payment,
    )

    payment = payment_service.create_payment(
        db_session, order.id, "test-unknown-1"
    )

    assert payment.status == "PENDING"
    assert payment.requires_review is True
    assert payment.review_reason is not None
    assert payment.next_reconciliation_at is not None


# ---------------------------------------------------------------------
# Test 8: Third failed attempt cancels order and releases reservation
# ---------------------------------------------------------------------

def test_third_failed_payment_cancels_order_and_releases_inventory(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-MAX-ATTEMPTS"
    )
    order = create_test_order(db_session, product)

    def fake_failed_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.FAILED,
            message="Definitive failure",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_failed_payment,
    )

    for attempt_number in range(1, 4):
        payment = payment_service.create_payment(
            db_session,
            order.id,
            f"test-max-attempt-{attempt_number}",
        )
        assert payment.status == "FAILED"

    saved_order = db_session.get(Order, order.id)
    assert saved_order is not None
    assert saved_order.status == "CANCELLED"

    inventory = get_inventory(db_session, product.id)
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 0

    payments = db_session.scalars(
        select(Payment)
        .where(Payment.order_id == order.id)
        .order_by(Payment.attempt_number)
    ).all()

    assert len(payments) == 3
    assert [p.attempt_number for p in payments] == [1, 2, 3]


# ---------------------------------------------------------------------
# Test 9: Fourth payment attempt is rejected
# ---------------------------------------------------------------------

def test_fourth_payment_attempt_is_rejected(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-FOURTH-ATTEMPT"
    )
    order = create_test_order(db_session, product)

    def fake_failed_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.FAILED,
            message="Definitive failure",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_failed_payment,
    )

    for attempt_number in range(1, 4):
        payment_service.create_payment(
            db_session,
            order.id,
            f"test-fourth-attempt-{attempt_number}",
        )

    with pytest.raises(HTTPException) as exc_info:
        payment_service.create_payment(
            db_session, order.id, "test-fourth-attempt-4"
        )

    assert exc_info.value.status_code == 409

    payments = db_session.scalars(
        select(Payment).where(Payment.order_id == order.id)
    ).all()
    assert len(payments) == 3


# ---------------------------------------------------------------------
# Test 10: Retry succeeds within the retry window
# ---------------------------------------------------------------------

def test_failed_payment_retry_succeeds_within_retry_window(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-RETRY-SUCCESS"
    )
    order = create_test_order(db_session, product)

    provider_call_count = 0

    def fake_payment(amount, idempotency_key):
        nonlocal provider_call_count
        provider_call_count += 1

        if provider_call_count == 1:
            return PaymentResult(
                status=ProviderPaymentStatus.FAILED,
                message="First attempt failed",
            )

        return PaymentResult(
            status=ProviderPaymentStatus.SUCCEEDED,
            provider_reference="provider-retry-success",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_payment,
    )

    first = payment_service.create_payment(
        db_session, order.id, "test-retry-attempt-1"
    )
    assert first.status == "FAILED"

    inventory = get_inventory(db_session, product.id)
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 2

    second = payment_service.create_payment(
        db_session, order.id, "test-retry-attempt-2"
    )

    assert second.status == "SUCCEEDED"
    assert first.attempt_number == 1
    assert second.attempt_number == 2

    saved_order = db_session.get(Order, order.id)
    assert saved_order is not None
    assert saved_order.status == "CONFIRMED"

    inventory = get_inventory(db_session, product.id)
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 2


# ---------------------------------------------------------------------
# Test 11: Expired retry window blocks another attempt
# ---------------------------------------------------------------------

def test_failed_payment_retry_is_rejected_after_retry_window(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-RETRY-EXPIRED"
    )
    order = create_test_order(db_session, product)

    def fake_failed_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.FAILED,
            message="Definitive failure",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_failed_payment,
    )

    first = payment_service.create_payment(
        db_session, order.id, "test-retry-expired-1"
    )
    assert first.status == "FAILED"
    assert first.retry_window_expires_at is not None

    db_session.execute(
        update(Payment)
        .where(Payment.id == first.id)
        .values(
            retry_window_expires_at=(
                first.retry_window_expires_at
                - timedelta(minutes=10)
            )
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        payment_service.create_payment(
            db_session, order.id, "test-retry-expired-2"
        )

    assert exc_info.value.status_code == 409

    payments = db_session.scalars(
        select(Payment).where(Payment.order_id == order.id)
    ).all()
    assert len(payments) == 1

    inventory = get_inventory(db_session, product.id)
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 2


# ---------------------------------------------------------------------
# Test 12: Pending payment blocks a second attempt
# ---------------------------------------------------------------------

def test_pending_payment_blocks_new_attempt(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-PENDING-BLOCK"
    )
    order = create_test_order(db_session, product)

    def fake_processing_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.PROCESSING,
            message="Still processing",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_processing_payment,
    )

    first = payment_service.create_payment(
        db_session, order.id, "test-pending-block-1"
    )

    assert first.status == "PENDING"
    assert first.requires_review is True

    with pytest.raises(HTTPException) as exc_info:
        payment_service.create_payment(
            db_session, order.id, "test-pending-block-2"
        )

    assert exc_info.value.status_code == 409

    payments = db_session.scalars(
        select(Payment).where(Payment.order_id == order.id)
    ).all()
    assert len(payments) == 1

    inventory = get_inventory(db_session, product.id)
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 2


# ---------------------------------------------------------------------
# Test 13: Successful payment persists provider reference
# ---------------------------------------------------------------------

def test_successful_payment_stores_provider_reference(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-PROVIDER-REFERENCE"
    )
    order = create_test_order(db_session, product)
    expected_reference = "provider-ref-success-001"

    def fake_successful_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.SUCCEEDED,
            provider_reference=expected_reference,
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_successful_payment,
    )

    payment = payment_service.create_payment(
        db_session, order.id, "test-provider-reference-1"
    )
    db_session.refresh(payment)

    assert payment.status == "SUCCEEDED"
    assert payment.provider_reference == expected_reference
    assert payment.requires_review is False


# ---------------------------------------------------------------------
# Test 14: Processing payment schedules reconciliation
# ---------------------------------------------------------------------

def test_processing_payment_schedules_reconciliation(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-RECONCILIATION-SCHEDULE"
    )
    order = create_test_order(db_session, product)

    def fake_processing_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.PROCESSING,
            message="Still processing",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_processing_payment,
    )

    payment = payment_service.create_payment(
        db_session, order.id, "test-reconciliation-schedule-1"
    )
    db_session.refresh(payment)

    assert payment.status == "PENDING"
    assert payment.requires_review is True
    assert payment.review_reason is not None
    assert payment.next_reconciliation_at is not None


# ---------------------------------------------------------------------
# Test 15: Unknown outcome preserves inventory reservation
# ---------------------------------------------------------------------

def test_unknown_provider_outcome_preserves_inventory_reservation(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-UNKNOWN-INVENTORY"
    )
    order = create_test_order(db_session, product)

    def fake_unknown_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.UNKNOWN,
            message="Outcome cannot be determined",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_unknown_payment,
    )

    payment = payment_service.create_payment(
        db_session, order.id, "test-unknown-inventory-1"
    )

    assert payment.status == "PENDING"
    assert payment.requires_review is True

    saved_order = db_session.get(Order, order.id)
    assert saved_order is not None
    assert saved_order.status == "PENDING_PAYMENT"

    inventory = get_inventory(db_session, product.id)
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 2


# ---------------------------------------------------------------------
# Test 16: An unresolved payment cannot be cleared by a new attempt
# ---------------------------------------------------------------------

def test_successful_payment_does_not_bypass_pending_review(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-PENDING-REVIEW"
    )
    order = create_test_order(db_session, product)

    def fake_processing_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.PROCESSING,
            message="Still processing",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_processing_payment,
    )

    first = payment_service.create_payment(
        db_session, order.id, "test-pending-review-1"
    )

    assert first.status == "PENDING"
    assert first.requires_review is True

    with pytest.raises(HTTPException) as exc_info:
        payment_service.create_payment(
            db_session, order.id, "test-pending-review-2"
        )

    assert exc_info.value.status_code == 409

    db_session.refresh(first)
    assert first.status == "PENDING"
    assert first.requires_review is True


# ---------------------------------------------------------------------
# Test 17: Missing inventory after provider success triggers review
# ---------------------------------------------------------------------

def test_missing_inventory_during_payment_requires_review(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-MISSING-INVENTORY"
    )
    order = create_test_order(db_session, product)

    inventory = get_inventory(db_session, product.id)
    db_session.delete(inventory)
    db_session.commit()

    def fake_successful_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.SUCCEEDED,
            provider_reference="provider-missing-inventory",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_successful_payment,
    )

    payment = payment_service.create_payment(
        db_session, order.id, "test-missing-inventory-1"
    )
    db_session.refresh(payment)

    assert payment.status == "PENDING"
    assert payment.requires_review is True
    assert payment.review_reason is not None

    saved_order = db_session.get(Order, order.id)
    assert saved_order is not None
    assert saved_order.status == "PENDING_PAYMENT"


# ---------------------------------------------------------------------
# Test 18: Provider receives exact order total
# ---------------------------------------------------------------------

def test_payment_uses_exact_order_total(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-EXACT-TOTAL", price="125.50"
    )
    order = create_test_order(db_session, product, quantity=2)
    received_amounts = []

    def fake_successful_payment(amount, idempotency_key):
        received_amounts.append(amount)
        return PaymentResult(
            status=ProviderPaymentStatus.SUCCEEDED,
            provider_reference="provider-exact-total",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_successful_payment,
    )

    payment = payment_service.create_payment(
        db_session, order.id, "test-exact-total-1"
    )

    assert payment.status == "SUCCEEDED"
    assert payment.amount == Decimal("251.00")
    assert received_amounts == [Decimal("251.00")]


# ---------------------------------------------------------------------
# Test 19: First failed attempt keeps order pending
# ---------------------------------------------------------------------

def test_failed_payment_keeps_order_pending_payment(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-ORDER-STATUS"
    )
    order = create_test_order(db_session, product)

    def fake_failed_payment(amount, idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.FAILED,
            message="Payment declined",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_failed_payment,
    )

    payment = payment_service.create_payment(
        db_session, order.id, "test-order-status-1"
    )

    saved_order = db_session.get(Order, order.id)
    assert payment.status == "FAILED"
    assert saved_order is not None
    assert saved_order.status == "PENDING_PAYMENT"

    inventory = get_inventory(db_session, product.id)
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 2


# ---------------------------------------------------------------------
# Test 20: Each retry gets a distinct provider idempotency key
# ---------------------------------------------------------------------

def test_payment_retry_uses_new_provider_idempotency_key(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-PROVIDER-KEYS"
    )
    order = create_test_order(db_session, product)
    provider_keys = []

    def fake_payment(amount, idempotency_key):
        provider_keys.append(idempotency_key)

        if len(provider_keys) == 1:
            return PaymentResult(
                status=ProviderPaymentStatus.FAILED,
                message="First attempt failed",
            )

        return PaymentResult(
            status=ProviderPaymentStatus.SUCCEEDED,
            provider_reference="provider-retry-key-success",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_payment,
    )

    payment_service.create_payment(
        db_session, order.id, "test-provider-key-retry-1"
    )
    payment_service.create_payment(
        db_session, order.id, "test-provider-key-retry-2"
    )

    assert len(provider_keys) == 2
    assert provider_keys[0] != provider_keys[1]
    assert all(provider_keys)
    assert "test-provider-key-retry-1" not in provider_keys
    assert "test-provider-key-retry-2" not in provider_keys


# ---------------------------------------------------------------------
# Test 21: Cancelled order cannot start a payment
# ---------------------------------------------------------------------

def test_cancelled_order_cannot_start_payment(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-CANCELLED-ORDER"
    )
    order = create_test_order(db_session, product)

    order.status = "CANCELLED"
    db_session.commit()

    provider_called = False

    def fake_provider_payment(amount, idempotency_key):
        nonlocal provider_called
        provider_called = True
        return PaymentResult(
            status=ProviderPaymentStatus.SUCCEEDED,
            provider_reference="unexpected-provider-success",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_provider_payment,
    )

    with pytest.raises(HTTPException) as exc_info:
        payment_service.create_payment(
            db_session, order.id, "test-cancelled-order-1"
        )

    assert exc_info.value.status_code == 409
    assert provider_called is False

    payments = db_session.scalars(
        select(Payment).where(Payment.order_id == order.id)
    ).all()
    assert len(payments) == 0


# ---------------------------------------------------------------------
# Test 22: Retry history is retained after success
# ---------------------------------------------------------------------

def test_successful_retry_records_two_distinct_attempts(
    db_session, monkeypatch
):
    product = create_test_product_and_inventory(
        db_session, "TEST-PAYMENT-ATTEMPT-HISTORY"
    )
    order = create_test_order(db_session, product)

    provider_call_count = 0

    def fake_payment(amount, idempotency_key):
        nonlocal provider_call_count
        provider_call_count += 1

        if provider_call_count == 1:
            return PaymentResult(
                status=ProviderPaymentStatus.FAILED,
                message="First attempt failed",
            )

        return PaymentResult(
            status=ProviderPaymentStatus.SUCCEEDED,
            provider_reference="provider-attempt-history-success",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        fake_payment,
    )

    payment_service.create_payment(
        db_session, order.id, "test-attempt-history-1"
    )
    payment_service.create_payment(
        db_session, order.id, "test-attempt-history-2"
    )

    payments = db_session.scalars(
        select(Payment)
        .where(Payment.order_id == order.id)
        .order_by(Payment.attempt_number)
    ).all()

    assert len(payments) == 2
    assert [p.attempt_number for p in payments] == [1, 2]
    assert [p.status for p in payments] == ["FAILED", "SUCCEEDED"]
    assert payments[0].idempotency_key != payments[1].idempotency_key

    inventory = get_inventory(db_session, product.id)
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 2
