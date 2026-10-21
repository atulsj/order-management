from decimal import Decimal

from app.integrations.payments.types import ProviderResult, ProviderStatus
from app.models import Inventory, Payment, Product
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services import payment_service, refund_service
from app.services.order_service import create_order
from app.services.payment_provider import PaymentResult, ProviderPaymentStatus


class SuccessfulRefundProvider:
    def refund(self, provider_reference, amount, currency, idempotency_key):
        return ProviderResult(
            ProviderStatus.SUCCEEDED,
            provider_reference="sim_refund_success",
        )


def test_paid_unshipped_cancellation_refunds_and_releases_stock(
    db_session, monkeypatch
):
    product = Product(
        sku="REFUND-001",
        name="Refund product",
        price=Decimal("50.00"),
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    inventory = Inventory(
        warehouse_id=1,
        product_id=product.id,
        quantity_on_hand=10,
        quantity_reserved=0,
    )
    db_session.add(inventory)
    db_session.commit()
    order = create_order(
        db_session,
        OrderCreate(
            items=[OrderItemCreate(product_id=product.id, quantity=2)]
        ),
    )

    monkeypatch.setattr(
        payment_service,
        "process_test_payment",
        lambda amount, key: PaymentResult(
            ProviderPaymentStatus.SUCCEEDED,
            provider_reference="sim_payment_success",
        ),
    )
    payment_service.create_payment(db_session, order.id, "refund-payment-key")
    monkeypatch.setattr(
        refund_service,
        "get_payment_provider",
        lambda: SuccessfulRefundProvider(),
    )

    refunded_order = refund_service.request_refund_cancellation(
        db_session,
        order.id,
        "refund-request-key",
        "customer:test",
    )

    db_session.refresh(inventory)
    payment = db_session.query(Payment).filter_by(order_id=order.id).one()
    assert refunded_order.status == "CANCELLED"
    assert payment.status == "REFUNDED"
    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 0
