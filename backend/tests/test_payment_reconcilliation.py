
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models import Inventory, Order, Payment, Product
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services import payment_service
from app.services.order_service import create_order
from app.services.payment_provider import (
    PaymentResult,
    ProviderPaymentStatus,
)


def create_uncertain_payment(db_session, sku):
    product = Product(
        sku=sku,
        name="Reconciliation test product",
        price=Decimal("100.00"),
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

    order = create_order(
        db_session,
        OrderCreate(
            items=[
                OrderItemCreate(
                    product_id=product.id,
                    quantity=2,
                )
            ]
        ),
    )

    payment = Payment(
        order_id=order.id,
        amount=order.total_amount,
        status="PENDING",
        idempotency_key=f"oms-{sku}",
        provider_idempotency_key=f"provider-{sku}",
        attempt_number=1,
        requires_review=True,
        review_reason="Provider outcome is uncertain",
        next_reconciliation_at=(
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ),
    )
    db_session.add(payment)
    db_session.commit()
    db_session.refresh(payment)

    return order.id, product.id, payment.id


def test_reconciliation_success_confirms_order_and_deducts_stock(
    db_session, monkeypatch
):
    order_id, product_id, payment_id = create_uncertain_payment(
        db_session, "RECON-SUCCESS"
    )

    def provider_success(idempotency_key):
        assert idempotency_key == "provider-RECON-SUCCESS"
        return PaymentResult(
            status=ProviderPaymentStatus.SUCCEEDED,
            provider_reference="reconciled-success-ref",
        )

    monkeypatch.setattr(
        payment_service,
        "get_test_payment_status",
        provider_success,
    )

    payment_service.reconcile_pending_payments(db_session)

    db_session.expire_all()
    order = db_session.get(Order, order_id)
    payment = db_session.get(Payment, payment_id)
    inventory = db_session.scalar(
        select(Inventory).where(Inventory.product_id == product_id)
    )

    assert order.status == "CONFIRMED"
    assert payment.status == "SUCCEEDED"
    assert payment.requires_review is False
    assert inventory.quantity_on_hand == 8
    assert inventory.quantity_reserved == 0


def test_reconciliation_unknown_status_keeps_payment_pending(
    db_session, monkeypatch
):
    order_id, product_id, payment_id = create_uncertain_payment(
        db_session, "RECON-UNKNOWN"
    )

    def provider_unknown(idempotency_key):
        return PaymentResult(
            status=ProviderPaymentStatus.UNKNOWN,
            message="Still unknown",
        )

    monkeypatch.setattr(
        payment_service,
        "get_test_payment_status",
        provider_unknown,
    )

    payment_service.reconcile_pending_payments(db_session)

    db_session.expire_all()
    order = db_session.get(Order, order_id)
    payment = db_session.get(Payment, payment_id)
    inventory = db_session.scalar(
        select(Inventory).where(Inventory.product_id == product_id)
    )

    assert order.status == "PENDING_PAYMENT"
    assert payment.status == "PENDING"
    assert payment.requires_review is True
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 2


def test_reconciliation_does_not_process_not_yet_due_payment(
    db_session, monkeypatch
):
    order_id, product_id, payment_id = create_uncertain_payment(
        db_session, "RECON-NOT-DUE"
    )

    payment = db_session.get(Payment, payment_id)
    payment.next_reconciliation_at = (
        datetime.now(timezone.utc) + timedelta(minutes=10)
    )
    db_session.commit()

    def provider_must_not_be_called(idempotency_key):
        raise AssertionError("Provider should not be queried yet")

    monkeypatch.setattr(
        payment_service,
        "get_test_payment_status",
        provider_must_not_be_called,
    )

    payment_service.reconcile_pending_payments(db_session)

    db_session.expire_all()
    payment = db_session.get(Payment, payment_id)
    order = db_session.get(Order, order_id)
    inventory = db_session.scalar(
        select(Inventory).where(Inventory.product_id == product_id)
    )

    assert payment.status == "PENDING"
    assert order.status == "PENDING_PAYMENT"
    assert inventory.quantity_reserved == 2
