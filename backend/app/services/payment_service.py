
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory import Inventory
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.payment import Payment
from app.services.payment_provider import (
    ProviderPaymentStatus,
    process_test_payment,
)

logger = logging.getLogger(__name__)

MAX_PAYMENT_ATTEMPTS = 3
RETRY_WINDOW = timedelta(minutes=5)
RECONCILIATION_DELAY = timedelta(minutes=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mark_for_review(payment: Payment, reason: str) -> None:
    """Keep uncertain payments pending; never treat uncertainty as failure."""
    payment.requires_review = True
    payment.review_reason = reason
    payment.next_reconciliation_at = _now() + RECONCILIATION_DELAY


def _lock_order(db: Session, order_id: int) -> Order | None:
    return db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
    )


def _release_reserved_inventory(db: Session, order_id: int) -> None:
    """Release this order's reservations without changing on-hand stock."""
    items = db.scalars(
        select(OrderItem)
        .where(OrderItem.order_id == order_id)
        .order_by(OrderItem.product_id)
    ).all()

    quantities_by_product: dict[int, int] = {}
    for item in items:
        quantities_by_product[item.product_id] = (
            quantities_by_product.get(item.product_id, 0)
            + item.quantity
        )

    product_ids = sorted(quantities_by_product)
    if not product_ids:
        return

    inventories = db.scalars(
        select(Inventory)
        .where(Inventory.product_id.in_(product_ids))
        .order_by(Inventory.product_id)
        .with_for_update()
    ).all()

    inventory_by_product = {
        inventory.product_id: inventory for inventory in inventories
    }

    if len(inventory_by_product) != len(product_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Inventory is missing for an order item",
        )

    # Validate all reservations before changing any of them.
    for product_id, quantity in quantities_by_product.items():
        inventory = inventory_by_product[product_id]
        if inventory.quantity_reserved < quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Inventory reservation is inconsistent",
            )

    for product_id, quantity in quantities_by_product.items():
        inventory_by_product[product_id].quantity_reserved -= quantity


def create_payment(
    db: Session,
    order_id: int,
    idempotency_key: str,
) -> Payment:
    # Phase 1: Lock the order and persist a payment attempt.

    order = _lock_order(db, order_id)

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    existing_payment = db.scalar(
        select(Payment).where(
            Payment.idempotency_key == idempotency_key
        )
    )

    if existing_payment is not None:
        if existing_payment.order_id != order_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key was used for another order",
            )

        if existing_payment.status == "PENDING":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Payment is pending; reconciliation is required",
            )

        return existing_payment

    if order.status != "PENDING_PAYMENT":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order is not awaiting payment",
        )

    attempts = db.scalars(
        select(Payment)
        .where(Payment.order_id == order_id)
        .order_by(Payment.attempt_number.desc())
        .with_for_update()
    ).all()

    latest_attempt = attempts[0] if attempts else None

    # Never create a second attempt while the outcome is uncertain.
    if latest_attempt is not None and latest_attempt.status == "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A payment is pending; reconciliation is required",
        )

    if latest_attempt is not None:
        if latest_attempt.status == "SUCCEEDED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Order already has a successful payment",
            )

        if latest_attempt.status == "FAILED":
            retry_expires_at = latest_attempt.retry_window_expires_at

            if retry_expires_at is None or _now() > retry_expires_at:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Payment retry window has expired",
                )

    attempt_number = (
        latest_attempt.attempt_number + 1 if latest_attempt else 1
    )

    if attempt_number > MAX_PAYMENT_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Maximum payment attempts reached",
        )

    # Generate and persist the provider key before contacting the provider.
    # It remains unchanged if we need to reconcile this same attempt.
    provider_key = f"oms-payment-{uuid4().hex}"

    payment = Payment(
        order_id=order.id,
        amount=order.total_amount,
        status="PENDING",
        idempotency_key=idempotency_key,
        provider_idempotency_key=provider_key,
        attempt_number=attempt_number,
        requires_review=False,
    )

    db.add(payment)

    try:
        db.commit()
        db.refresh(payment)
    except IntegrityError:
        db.rollback()
        logger.exception("Payment attempt insert conflicted")

        existing_payment = db.scalar(
            select(Payment).where(
                Payment.idempotency_key == idempotency_key
            )
        )

        if existing_payment is not None:
            if existing_payment.order_id != order_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key was used for another order",
                )
            if existing_payment.status == "PENDING":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Payment is pending; reconciliation is required",
                )
            return existing_payment

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment attempt conflicted with another request",
        )

    payment_id = payment.id
    provider_key = payment.provider_idempotency_key
    amount = payment.amount

    # Phase 2: Call the provider outside the PostgreSQL transaction.
    try:
        result = process_test_payment(amount, provider_key)
    except Exception as exc:
        logger.exception(
            "Provider outcome uncertain for payment_id=%s", payment_id
        )

        # Persist the review flag. Do not mark a timeout as FAILED.
        try:
            payment = db.scalar(
                select(Payment)
                .where(Payment.id == payment_id)
                .with_for_update()
            )
            if payment is not None and payment.status == "PENDING":
                _mark_for_review(payment, "Provider request failed or timed out")
                db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "Could not save review flag for payment_id=%s", payment_id
            )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment outcome is uncertain; reconciliation is required",
        ) from exc

    # Phase 3: Save the outcome and apply business changes atomically.
    try:
        order = _lock_order(db, order_id)
        payment = db.scalar(
            select(Payment)
            .where(Payment.id == payment_id)
            .with_for_update()
        )

        if order is None or payment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order or payment not found",
            )

        # Another worker may have reconciled this attempt already.
        if payment.status != "PENDING":
            return payment

        payment.provider_reference = result.provider_reference

        if result.status in (
            ProviderPaymentStatus.PROCESSING,
            ProviderPaymentStatus.UNKNOWN,
        ):
            _mark_for_review(
                payment,
                result.message or f"Provider status: {result.status.value}",
            )
            db.commit()
            db.refresh(payment)
            return payment

        if result.status == ProviderPaymentStatus.FAILED:
            payment.status = "FAILED"
            payment.requires_review = False
            payment.review_reason = None
            payment.next_reconciliation_at = None

            if attempt_number < MAX_PAYMENT_ATTEMPTS:
                payment.retry_window_expires_at = _now() + RETRY_WINDOW
            else:
                # Third definitive failure: cancel and release reservations.
                if order.status == "PENDING_PAYMENT":
                    _release_reserved_inventory(db, order_id)
                    order.status = "CANCELLED"

            db.commit()
            db.refresh(payment)
            return payment

        if result.status != ProviderPaymentStatus.SUCCEEDED:
            _mark_for_review(payment, "Unrecognized provider status")
            db.commit()
            db.refresh(payment)
            return payment

        if order.status != "PENDING_PAYMENT":
            # Do not consume inventory if the order is no longer payable.
            _mark_for_review(
                payment,
                "Provider reported success but order is no longer pending",
            )
            db.commit()
            db.refresh(payment)
            return payment

        items = db.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order_id)
            .order_by(OrderItem.product_id)
        ).all()

        product_ids = sorted({item.product_id for item in items})
        inventories = []

        if product_ids:
            inventories = db.scalars(
                select(Inventory)
                .where(Inventory.product_id.in_(product_ids))
                .order_by(Inventory.product_id)
                .with_for_update()
            ).all()

        inventory_by_product = {
            inventory.product_id: inventory for inventory in inventories
        }

        if len(inventory_by_product) != len(product_ids):
            _mark_for_review(payment, "Inventory is missing after provider success")
            db.commit()
            db.refresh(payment)
            return payment

        for item in items:
            inventory = inventory_by_product[item.product_id]
            if (
                inventory.quantity_reserved < item.quantity
                or inventory.quantity_on_hand < item.quantity
            ):
                _mark_for_review(
                    payment, "Inventory reservation is inconsistent after success"
                )
                db.commit()
                db.refresh(payment)
                return payment

        for item in items:
            inventory = inventory_by_product[item.product_id]
            inventory.quantity_reserved -= item.quantity
            inventory.quantity_on_hand -= item.quantity

        payment.status = "SUCCEEDED"
        payment.requires_review = False
        payment.review_reason = None
        payment.next_reconciliation_at = None
        payment.retry_window_expires_at = None
        order.status = "CONFIRMED"

        db.commit()
        db.refresh(payment)
        return payment

    except Exception:
        db.rollback()
        logger.exception(
            "Failed to persist provider result for payment_id=%s", payment_id
        )
        raise
