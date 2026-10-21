# Payments, refunds, and provider failures

## Provider abstraction

The domain depends on `PaymentProvider`, not Stripe SDK objects. Providers normalize results to:

- `SUCCEEDED`
- `FAILED`
- `PROCESSING`
- `UNKNOWN`

Each result may include provider reference, safe message, and payment client secret.

Two adapters exist:

- Simulator: stores shared transactions in PostgreSQL; safe across local API/worker replicas.
- Stripe: creates PaymentIntents, queries intent state, creates/retrieves refunds, and validates webhooks.

The simulator is for learning and deterministic integration tests. It is not a card processor.

## Two idempotency layers

### Client key

The caller sends `Idempotency-Key`. The OMS binds it to:

- authenticated principal,
- payment operation,
- order ID,
- request fingerprint.

Same operation/key returns the same completed record. A different principal/order/input returns 409.

### Provider key

The OMS creates a random provider key per attempt and persists it before the call. It never sends the customer’s raw key to the provider.

This separation prevents external coupling and ensures each retry attempt has a distinct provider identity while reconciliation reuses the same attempt key.

## Why timeout is not failure

A timeout answers only “the OMS did not receive a response.” It does not answer whether the provider charged the customer.

Therefore:

- timeout/transport exception -> payment remains pending and review-required;
- inventory remains reserved;
- no second payment attempt is allowed;
- reconciliation queries the same provider transaction;
- only a definitive failed result opens another attempt.

Marking timeout as failed could double-charge a customer.

## Retry policy

- Maximum attempts: 3.
- Definitive failed attempt retry window: 5 minutes.
- Uncertain pending attempt: no new attempt; reconcile instead.
- Third definitive failure: cancel order and release reservations.

These are current business settings in code, not universal commerce rules. In a real deployment, retry limits and windows should be configuration approved by product, fraud, and payment teams.

## Reconciliation schedule

When a payment intent row commits, it already has:

- `requires_review = true`,
- first `next_reconciliation_at`,
- a 24-hour `reconciliation_deadline_at`.

Each uncertain lookup increases `reconciliation_attempts`. Delay doubles with bounded jitter and caps at 60 minutes. The deadline remains fixed.

At deadline:

- status remains pending,
- `requires_review` remains true,
- automatic next time becomes null,
- review reason records deadline exceeded,
- operator intervention is required.

Never resolve an overdue uncertain payment by guessing.

## Stripe crash recovery

The provider key is included in PaymentIntent metadata. If the API loses the PaymentIntent ID after Stripe accepted the request, reconciliation searches by that key. Normal lookups use the saved provider reference.

Webhook signatures are verified over raw bytes. Event ID uniqueness prevents duplicate application.

Stripe secrets:

- secret key stays backend-only;
- publishable key may go to browser runtime configuration;
- webhook secret is distinct from API key;
- client secret is returned only for the active browser payment flow and must not be logged.

## Refund behavior

Paid, unshipped cancellation:

1. verify no consumed allocation;
2. persist refund intent/key and `CANCELLATION_PENDING`;
3. commit;
4. call provider outside transaction;
5. apply result under locks.

If process death loses refund response:

- no provider reference: retry refund creation using same idempotency key;
- provider reference present: retrieve refund.

Successful refund releases reservation. Failed refund restores confirmed order. Unknown/processing keeps cancellation pending and review-required.

## Failure table

| Failure | Expected state | Operator/customer action |
|---|---|---|
| Validation before provider | no attempt | correct request |
| Provider definitive decline | failed attempt, reservation retained | retry within window |
| Third decline | order cancelled, reservation released | create a new order |
| Provider timeout | pending/review, reservation retained | wait for reconciliation |
| Processing for >24h | pending, deadline review | operator checks provider dashboard |
| Success after OMS cancellation | payment review | verify charge, refund if appropriate |
| Missing/inconsistent reservation | payment review | inventory incident runbook |
| Duplicate webhook | no state change | none |
| Invalid webhook signature | HTTP 400 | inspect endpoint secret/source |
| Refund timeout | refund review, cancellation pending | reconcile/provider dashboard |
| Refund failure | order confirmed | communicate and retry per policy |

## Simulator scenarios

Set `SIMULATOR_OUTCOME` before recreating API/worker:

```powershell
$env:SIMULATOR_OUTCOME = "PROCESSING"
docker compose up -d --force-recreate api worker beat
```

Accepted values are `SUCCEEDED`, `FAILED`, `PROCESSING`, and `UNKNOWN`.

The simulator persists the first result for an idempotency key. Changing the environment does not change an existing simulated transaction; use a new order/payment key.

## Stripe test mode

Set:

```text
PAYMENT_PROVIDER=stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

Use Stripe CLI to forward events:

```powershell
stripe listen --forward-to http://localhost:8000/api/v1/payments/webhooks/stripe
```

Do not use live credentials or real customer data in the learning environment.
