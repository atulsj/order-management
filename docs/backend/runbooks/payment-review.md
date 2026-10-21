# Runbook: uncertain payment or reconciliation deadline

## Trigger

- payment `requires_review = true`;
- no `next_reconciliation_at` because deadline elapsed;
- payment review count/age alert;
- customer reports charge but order is not confirmed.

## Safety rule

Do not create another charge and do not mark failed solely because the OMS timed out.

## Triage

1. Capture payment ID, order ID, provider reference, provider idempotency key, attempt number, deadline, and request ID. Do not paste secret/client values into tickets.
2. Inspect order status and active allocations.
3. Inspect all payment attempts for the order in attempt order.
4. Check worker/broker health and reconciliation logs.
5. Query provider dashboard/API by provider reference. If absent, use the provider key metadata/search path.
6. Compare amount, currency, order metadata, and provider status.

## Resolution

- **Provider succeeded, order pending:** run idempotent reconciliation; it should confirm.
- **Provider failed definitively:** reconciliation records failure and opens retry/cancels according to attempt number.
- **Provider processing:** keep reservation; agree next review time.
- **Provider has no transaction and can prove no charge:** follow approved manual resolution; do not infer from search failure alone.
- **Order cancelled but provider succeeded:** initiate/refollow refund; do not reconfirm cancelled stock blindly.
- **Amount/order mismatch:** security/payment incident; do not auto-resolve.

## Validate after resolution

- exactly one successful payment at most;
- order state agrees with payment/refund;
- active reservation is retained for confirmed unshipped order;
- no on-hand decrement before shipment;
- order event exists;
- outbox event is published or pending, not dead-lettered.

## Escalation

Escalate to payment provider support with non-secret IDs if provider state cannot be determined. Escalate inventory incident separately if reservation arithmetic is inconsistent.
