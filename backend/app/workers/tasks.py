import logging
from datetime import UTC, datetime, timedelta

from celery import shared_task
from sqlalchemy import select

from app.core.config import get_settings
from app.database.connection import SessionLocal
from app.integrations.notifications import send_email
from app.models.integration_event import OutboxEvent
from app.models.order import Order
from app.services.order_service import cancel_order
from app.services.payment_service import reconcile_pending_payments
from app.services.refund_service import reconcile_pending_refunds
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def reconcile_payments(self) -> int:
    with SessionLocal() as db:
        return reconcile_pending_payments(db)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def reconcile_refunds(self) -> int:
    with SessionLocal() as db:
        return reconcile_pending_refunds(db)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def dispatch_outbox(self, batch_size: int = 100) -> int:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        events = db.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.published_at.is_(None),
                OutboxEvent.dead_lettered_at.is_(None),
                OutboxEvent.available_at <= now,
            )
            .order_by(OutboxEvent.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        for event in events:
            event.attempts += 1
            try:
                celery_app.send_task(
                    "app.workers.tasks.process_domain_event",
                    args=[event.event_type, event.payload],
                    queue="notifications",
                )
                event.published_at = now
                event.last_error = None
            except Exception as exc:
                event.last_error = str(exc)[:2000]
                if event.attempts >= 10:
                    event.dead_lettered_at = now
                else:
                    event.available_at = now + timedelta(
                        seconds=min(3600, 2**event.attempts)
                    )
        db.commit()
        return len(events)


@shared_task
def process_domain_event(event_type: str, payload: dict) -> None:
    logger.info("domain_event type=%s payload=%s", event_type, payload)
    recipient = payload.get("recipient_email")
    if recipient:
        send_email(
            recipient,
            f"OMS update: {event_type}",
            f"Your order update is ready. Reference: {payload.get('order_id', 'n/a')}",
        )


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def expire_orders(self, batch_size: int = 100) -> int:
    cutoff = datetime.now(UTC) - timedelta(
        minutes=get_settings().order_reservation_minutes
    )
    expired = 0
    with SessionLocal() as db:
        order_ids = db.scalars(
            select(Order.id)
            .where(
                Order.status == "PENDING_PAYMENT",
                Order.created_at <= cutoff,
            )
            .order_by(Order.id)
            .limit(batch_size)
        ).all()
        for order_id in order_ids:
            try:
                cancel_order(db, order_id, "system:reservation-expiry")
                expired += 1
            except Exception:
                db.rollback()
                logger.exception("Could not expire order_id=%s", order_id)
        return expired
