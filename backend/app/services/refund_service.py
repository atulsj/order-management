from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.payments.factory import get_payment_provider
from app.integrations.payments.types import ProviderStatus
from app.models.allocation import InventoryAllocation
from app.models.integration_event import OutboxEvent
from app.models.order import Order
from app.models.order_event import OrderEvent
from app.models.order_item import OrderItem
from app.models.payment import Payment
from app.models.refund import Refund
from app.services.order_service import get_order, release_reserved_allocations


def request_refund_cancellation(
    db: Session,
    order_id: int,
    idempotency_key: str,
    actor_subject: str,
) -> Order:
    try:
        order = db.scalar(
            select(Order).where(Order.id == order_id).with_for_update()
        )
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        existing = db.scalar(
            select(Refund).where(Refund.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if existing.payment.order_id != order_id:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Refund idempotency key was used for another order",
                )
            return get_order(db, order_id)
        if order.status not in {"CONFIRMED", "CANCELLATION_PENDING"}:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Only paid, unfulfilled orders can enter the refund workflow",
            )
        consumed = db.scalar(
            select(InventoryAllocation.id)
            .join(OrderItem, OrderItem.id == InventoryAllocation.order_item_id)
            .where(
                OrderItem.order_id == order.id,
                InventoryAllocation.status == "CONSUMED",
            )
            .limit(1)
        )
        if consumed is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Shipped orders require the returns workflow",
            )
        payment = db.scalar(
            select(Payment)
            .where(
                Payment.order_id == order.id,
                Payment.status == "SUCCEEDED",
            )
            .order_by(Payment.attempt_number.desc())
            .with_for_update()
        )
        if payment is None or payment.provider_reference is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Successful payment was not found"
            )
        provider_key = f"oms-refund-{uuid4().hex}"
        refund = Refund(
            payment_id=payment.id,
            idempotency_key=idempotency_key,
            provider_idempotency_key=provider_key,
            amount=payment.amount,
            status="PENDING",
        )
        order.status = "CANCELLATION_PENDING"
        db.add(refund)
        db.add(
            OrderEvent(
                order_id=order.id,
                event_type="REFUND_REQUESTED",
                actor_subject=actor_subject,
                data={"payment_id": payment.id},
            )
        )
        db.commit()
        db.refresh(refund)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Refund request conflicted"
        ) from exc
    except Exception:
        db.rollback()
        raise

    try:
        result = get_payment_provider().refund(
            payment.provider_reference,
            payment.amount,
            order.currency,
            provider_key,
        )
    except Exception as exc:
        _mark_refund_review(db, refund.id, "Refund provider outcome is uncertain")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Refund outcome is uncertain and requires reconciliation",
        ) from exc

    _apply_refund_result(db, refund.id, result.status, result.provider_reference)
    return get_order(db, order_id)


def _mark_refund_review(db: Session, refund_id: int, reason: str) -> None:
    refund = db.scalar(
        select(Refund).where(Refund.id == refund_id).with_for_update()
    )
    if refund is not None and refund.status == "PENDING":
        refund.status = "REVIEW"
        refund.review_reason = reason
        db.commit()


def _apply_refund_result(
    db: Session,
    refund_id: int,
    provider_status: ProviderStatus,
    provider_reference: str | None,
) -> None:
    try:
        preview = db.get(Refund, refund_id)
        if preview is None:
            return
        payment_preview = db.get(Payment, preview.payment_id)
        if payment_preview is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Refund payment is missing")
        order = db.scalar(
            select(Order)
            .where(Order.id == payment_preview.order_id)
            .with_for_update()
        )
        payment = db.scalar(
            select(Payment)
            .where(Payment.id == payment_preview.id)
            .with_for_update()
        )
        refund = db.scalar(
            select(Refund).where(Refund.id == refund_id).with_for_update()
        )
        if refund is None or refund.status not in {"PENDING", "REVIEW"}:
            return
        if payment is None or order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Refund target is missing")
        refund.provider_reference = provider_reference
        if provider_status == ProviderStatus.SUCCEEDED:
            release_reserved_allocations(db, order.id)
            refund.status = "SUCCEEDED"
            refund.review_reason = None
            payment.status = "REFUNDED"
            order.status = "CANCELLED"
            db.add(
                OrderEvent(
                    order_id=order.id,
                    event_type="REFUND_SUCCEEDED",
                    data={"refund_id": refund.id},
                )
            )
            db.add(
                OutboxEvent(
                    event_type="refund.succeeded",
                    aggregate_type="refund",
                    aggregate_id=str(refund.id),
                    payload={"refund_id": refund.id, "order_id": order.id},
                    attempts=0,
                )
            )
        elif provider_status == ProviderStatus.FAILED:
            refund.status = "FAILED"
            refund.review_reason = None
            order.status = "CONFIRMED"
        else:
            refund.status = "REVIEW"
            refund.review_reason = "Refund is still processing"
        db.commit()
    except Exception:
        db.rollback()
        raise


def reconcile_pending_refunds(db: Session, limit: int = 100) -> int:
    refund_ids = db.scalars(
        select(Refund.id)
        .where(Refund.status.in_(["PENDING", "REVIEW"]))
        .order_by(Refund.id)
        .limit(limit)
    ).all()
    attempted = 0
    for refund_id in refund_ids:
        refund = db.get(Refund, refund_id)
        if refund is None:
            continue
        payment = db.get(Payment, refund.payment_id)
        if payment is None or payment.provider_reference is None:
            continue
        try:
            if refund.provider_reference:
                result = get_payment_provider().get_refund(
                    refund.provider_reference,
                    refund.provider_idempotency_key,
                )
            else:
                result = get_payment_provider().refund(
                    payment.provider_reference,
                    refund.amount,
                    order.currency,
                    refund.provider_idempotency_key,
                )
            attempted += 1
            _apply_refund_result(
                db, refund.id, result.status, result.provider_reference
            )
        except Exception:
            db.rollback()
    return attempted
