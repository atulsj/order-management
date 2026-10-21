
import logging
import random
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.payments.factory import get_payment_provider
from app.models.allocation import InventoryAllocation
from app.models.integration_event import OutboxEvent
from app.models.inventory import Inventory
from app.models.order import Order
from app.models.order_event import OrderEvent
from app.models.order_item import OrderItem
from app.models.payment import Payment
from app.services.payment_provider import (
    get_test_payment_status,
    process_test_payment,
)

logger = logging.getLogger(__name__)

MAX_PAYMENT_ATTEMPTS = 3
RETRY_WINDOW = timedelta(minutes=5)
RECONCILIATION_DELAY = timedelta(minutes=1)


def _now() -> datetime:
    return datetime.now(UTC)


def _mark_for_review(payment: Payment, reason: str) -> None:
    """Keep uncertain payments pending; never treat uncertainty as failure."""
    now = _now()
    settings = get_settings()
    payment.requires_review = True
    payment.review_reason = reason
    if payment.reconciliation_deadline_at is None:
        payment.reconciliation_deadline_at = now + timedelta(
            hours=settings.reconciliation_deadline_hours
        )
    if now >= payment.reconciliation_deadline_at:
        payment.review_reason = f"Reconciliation deadline exceeded: {reason}"
        payment.next_reconciliation_at = None
        return
    payment.reconciliation_attempts += 1
    minutes = min(60, 2 ** min(payment.reconciliation_attempts - 1, 6))
    jitter = random.uniform(0.8, 1.2)
    candidate = now + timedelta(minutes=minutes * jitter)
    payment.next_reconciliation_at = min(candidate, payment.reconciliation_deadline_at)


def _create_provider_payment(
    amount,
    provider_key: str,
    order_id: int,
    currency: str,
):
    settings = get_settings()
    if settings.payment_provider == "simulator":
        return process_test_payment(amount, provider_key)
    return get_payment_provider().create_payment(
        amount, currency, provider_key, order_id
    )


def _query_provider_payment(payment: Payment):
    settings = get_settings()
    if settings.payment_provider == "simulator":
        return get_test_payment_status(payment.provider_idempotency_key)
    return get_payment_provider().get_payment(
        payment.provider_reference or "",
        payment.provider_idempotency_key,
    )


def _lock_order(db: Session, order_id: int) -> Order | None:
    return db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
    )


def _release_reserved_inventory(db: Session, order_id: int) -> None:
    """Release this order's reservations without changing on-hand stock."""
    allocations = db.scalars(
        select(InventoryAllocation)
        .join(OrderItem, OrderItem.id == InventoryAllocation.order_item_id)
        .where(
            OrderItem.order_id == order_id,
            InventoryAllocation.status == "RESERVED",
        )
        .order_by(InventoryAllocation.inventory_id, InventoryAllocation.id)
        .with_for_update()
    ).all()
    inventory_ids = sorted({allocation.inventory_id for allocation in allocations})
    if not inventory_ids:
        return
    inventories = db.scalars(
        select(Inventory)
        .where(Inventory.id.in_(inventory_ids))
        .order_by(Inventory.id)
        .with_for_update()
    ).all()
    inventory_by_id = {inventory.id: inventory for inventory in inventories}
    if len(inventory_by_id) != len(inventory_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Inventory is missing for an order item",
        )
    for allocation in allocations:
        inventory = inventory_by_id[allocation.inventory_id]
        if inventory.quantity_reserved < allocation.quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Inventory reservation is inconsistent",
            )
    for allocation in allocations:
        inventory_by_id[allocation.inventory_id].quantity_reserved -= allocation.quantity
        allocation.status = "RELEASED"


def apply_payment_result(
    db: Session,
    payment_id: int,
    result,
    actor_subject: str | None = None,
    reconciled: bool = False,
) -> Payment:
    preview = db.get(Payment, payment_id)
    if preview is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    order = _lock_order(db, preview.order_id)
    payment = db.scalar(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    )
    if order is None or payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order or payment not found")
    if payment.status != "PENDING":
        return payment
    if reconciled:
        payment.last_reconciled_at = _now()
    if result.provider_reference:
        payment.provider_reference = result.provider_reference
    outcome = result.status.value
    if outcome in {"PROCESSING", "UNKNOWN"}:
        _mark_for_review(
            payment,
            result.message or f"Provider status: {outcome}",
        )
    elif outcome == "FAILED":
        payment.status = "FAILED"
        payment.requires_review = False
        payment.review_reason = None
        payment.next_reconciliation_at = None
        if payment.attempt_number < MAX_PAYMENT_ATTEMPTS:
            payment.retry_window_expires_at = _now() + RETRY_WINDOW
        elif order.status == "PENDING_PAYMENT":
            _release_reserved_inventory(db, order.id)
            order.status = "CANCELLED"
    elif outcome == "SUCCEEDED":
        if order.status != "PENDING_PAYMENT":
            _mark_for_review(
                payment,
                "Provider reported success but order is no longer pending",
            )
        else:
            payment.status = "SUCCEEDED"
            payment.requires_review = False
            payment.review_reason = None
            payment.next_reconciliation_at = None
            payment.retry_window_expires_at = None
            order.status = "CONFIRMED"
            db.add(
                OrderEvent(
                    order_id=order.id,
                    event_type=(
                        "PAYMENT_RECONCILED"
                        if reconciled
                        else "PAYMENT_CONFIRMED"
                    ),
                    actor_subject=actor_subject,
                    data={"payment_id": payment.id},
                )
            )
            db.add(
                OutboxEvent(
                    event_type="payment.succeeded",
                    aggregate_type="payment",
                    aggregate_id=str(payment.id),
                    payload={"payment_id": payment.id, "order_id": order.id},
                    attempts=0,
                )
            )
    else:
        _mark_for_review(payment, "Unrecognized provider status")
    db.commit()
    db.refresh(payment)
    object.__setattr__(
        payment, "client_secret", getattr(result, "client_secret", None)
    )
    return payment


def create_payment(
    db: Session,
    order_id: int,
    idempotency_key: str,
    principal_subject: str | None = None,
    request_fingerprint: str | None = None,
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
        if (
            principal_subject is not None
            and existing_payment.principal_subject not in {None, principal_subject}
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key was used by another principal",
            )
        if (
            request_fingerprint is not None
            and existing_payment.request_fingerprint not in {None, request_fingerprint}
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key was reused with different input",
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
        principal_subject=principal_subject,
        request_fingerprint=request_fingerprint
        or sha256(f"payment:{order_id}".encode()).hexdigest(),
        reconciliation_deadline_at=_now()
        + timedelta(hours=get_settings().reconciliation_deadline_hours),
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
        result = _create_provider_payment(
            amount,
            provider_key,
            order_id,
            order.currency,
        )
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

    try:
        return apply_payment_result(
            db,
            payment_id,
            result,
            actor_subject=principal_subject,
        )
    except Exception:
        db.rollback()
        logger.exception(
            "Failed to persist provider result for payment_id=%s", payment_id
        )
        raise


def reconcile_pending_payments(db: Session) -> int:
    """Reconcile due, uncertain payments against the provider.

    Returns the number of provider queries attempted.
    """
    now = _now()

    payment_ids = db.scalars(
        select(Payment.id)
        .where(
            Payment.status == "PENDING",
            Payment.requires_review.is_(True),
            Payment.next_reconciliation_at.is_not(None),
            Payment.next_reconciliation_at <= now,
        )
        .order_by(Payment.id)
    ).all()

    reconciled_count = 0

    for payment_id in payment_ids:
        # Read the provider key first. Do not hold a database transaction
        # open while making the external provider request.
        payment = db.get(Payment, payment_id)
        if payment is None or payment.status != "PENDING":
            continue

        order_id = payment.order_id

        try:
            result = _query_provider_payment(payment)
            reconciled_count += 1
        except Exception:
            logger.exception(
                "Provider status lookup failed for payment_id=%s",
                payment_id,
            )

            try:
                order = _lock_order(db, order_id)
                payment = db.scalar(
                    select(Payment)
                    .where(Payment.id == payment_id)
                    .with_for_update()
                )

                if (
                    order is not None
                    and payment is not None
                    and payment.status == "PENDING"
                    and payment.requires_review
                ):
                    payment.last_reconciled_at = _now()
                    _mark_for_review(
                        payment,
                        "Provider status lookup failed; outcome remains uncertain",
                    )
                    db.commit()
                else:
                    db.rollback()
            except Exception:
                db.rollback()
                logger.exception(
                    "Could not update reconciliation state for payment_id=%s",
                    payment_id,
                )

            continue

        try:
            apply_payment_result(
                db,
                payment_id,
                result,
                reconciled=True,
            )
        except Exception:
            db.rollback()
            logger.exception(
                "Reconciliation failed while saving payment_id=%s",
                payment_id,
            )
            raise

    return reconciled_count
