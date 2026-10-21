

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import Inventory, Order, Payment, Product
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services import payment_service
from app.services.order_service import cancel_order, create_order
from app.services.payment_provider import (
    PaymentResult,
    ProviderPaymentStatus,
)


def test_cancellation_during_provider_call_does_not_corrupt_inventory(
    db_session, monkeypatch
):
    product = Product(
        sku="RACE-001",
        name="Race test product",
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
    order_id = order.id
    product_id = product.id

    provider_started = Event()
    allow_provider_to_finish = Event()
    engine = db_session.get_bind()
    TestSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def slow_success(amount, idempotency_key):
        provider_started.set()
        if not allow_provider_to_finish.wait(timeout=10):
            raise TimeoutError("Test did not release provider call")
        return PaymentResult(
            status=ProviderPaymentStatus.SUCCEEDED,
            provider_reference="race-provider-ref",
        )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        slow_success,
    )

    def start_payment():
        with TestSession() as session:
            try:
                return payment_service.create_payment(
                    session, order_id, "race-payment-key"
                )
            except Exception as exc:
                session.rollback()
                return exc

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(start_payment)

        assert provider_started.wait(timeout=10)

        with TestSession() as cancel_session:
            try:
                cancel_order(cancel_session, order_id)
                cancel_result = "cancelled"
            except HTTPException as exc:
                cancel_session.rollback()
                cancel_result = exc.status_code

        allow_provider_to_finish.set()
        payment_result = future.result(timeout=20)

    assert cancel_result in {"cancelled", 409}
    assert not isinstance(payment_result, TimeoutError)
    db_session.expire_all()
    final_order = db_session.get(Order, order_id)
    final_inventory = db_session.scalar(
        select(Inventory).where(Inventory.product_id == product_id)
    )
    payments = db_session.scalars(
        select(Payment).where(Payment.order_id == order_id)
    ).all()

    assert final_order is not None
    assert final_inventory is not None
    assert len(payments) == 1

    # A successful provider response must not silently confirm an order
    # that was cancelled and whose reservation was already released.
    assert not (
        final_order.status == "CONFIRMED"
        and final_inventory.quantity_reserved == 0
        and final_inventory.quantity_on_hand == 10
    )
