from datetime import UTC, datetime
from typing import Any, cast

import stripe
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.payments.types import ProviderResult, ProviderStatus
from app.models.integration_event import WebhookInbox
from app.models.payment import Payment
from app.services.payment_service import apply_payment_result


def process_stripe_webhook(db: Session, payload: bytes, signature: str) -> bool:
    secret = get_settings().stripe_webhook_secret
    if secret is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Stripe webhook secret is not configured",
        )
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, secret.get_secret_value()
        )
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Stripe webhook") from exc
    event_id = str(event["id"])
    inbox = WebhookInbox(
        provider="stripe",
        event_id=event_id,
        event_type=str(event["type"]),
        payload=cast(dict[str, Any], cast(Any, event).to_dict_recursive()),
    )
    db.add(inbox)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False

    event_type = str(event["type"])
    provider_reference = str(event["data"]["object"]["id"])
    payment = db.scalar(
        select(Payment).where(Payment.provider_reference == provider_reference)
    )
    if payment is not None and payment.status == "PENDING":
        provider_status = ProviderStatus.UNKNOWN
        if event_type == "payment_intent.succeeded":
            provider_status = ProviderStatus.SUCCEEDED
        elif event_type == "payment_intent.payment_failed":
            provider_status = ProviderStatus.FAILED
        elif event_type in {
            "payment_intent.processing",
            "payment_intent.requires_action",
        }:
            provider_status = ProviderStatus.PROCESSING
        apply_payment_result(
            db,
            payment.id,
            ProviderResult(
                status=provider_status,
                provider_reference=provider_reference,
                message=f"Stripe webhook: {event_type}",
            ),
            actor_subject="stripe:webhook",
            reconciled=True,
        )
    inbox.processed_at = datetime.now(UTC)
    db.commit()
    return True
