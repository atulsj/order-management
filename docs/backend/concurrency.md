# Concurrency and race safety

## Isolation model

The application uses PostgreSQL’s default `READ COMMITTED` isolation plus explicit row locks. `READ COMMITTED` alone does not prevent two requests from both observing the same available inventory. `SELECT ... FOR UPDATE` creates the required serialization point.

Database constraints remain the last line of defense:

- nonnegative on-hand and reserved,
- reserved not above on-hand,
- unique warehouse/product inventory,
- unique payment client/provider keys,
- unique order/payment attempt number,
- unique webhook event ID,
- unique shipment/allocation membership.

## Global lock ordering

Code that touches several aggregate rows follows this order:

1. Order
2. Payment
3. Refund or shipment
4. Allocation rows ordered by inventory ID then allocation ID
5. Inventory rows ordered by inventory ID

New-order allocation has no existing order row, so it locks:

1. Product rows ordered by product ID
2. Inventory rows ordered by product, warehouse priority, warehouse ID, inventory ID

Consistent ordering reduces cyclic waits. It does not make deadlocks mathematically impossible when new code violates the convention, so deadlock errors should remain visible and retryable at an appropriate boundary.

## Competing checkouts

Example: inventory has 5 available; request A asks for 4 and B asks for 3.

1. A locks inventory.
2. B waits.
3. A verifies 5, reserves 4, commits.
4. B obtains lock and sees available 1.
5. B receives 409 insufficient stock.

At no point can committed reserved quantity exceed on-hand.

## Multi-product deadlocks

Without ordering:

- A locks product 1 then waits for product 2.
- B locks product 2 then waits for product 1.

The implementation sorts IDs so both lock 1 then 2. Inventory follows the same deterministic principle.

## Payment versus cancellation

The payment provider call runs without an order lock. Cancellation may commit while the provider is processing.

When provider success returns, the transition locks and re-reads the order:

- if still pending, it confirms;
- if cancelled or changed, it does not reconfirm and flags review.

This is deliberate optimistic orchestration around an external system. Keeping the lock across the provider call would block cancellation but create worse database/network coupling and still could not provide a distributed atomic commit.

## Payment versus payment

Creation locks the order, then all attempt rows. Only one new attempt number can commit. Unique `(order_id, attempt_number)` and idempotency constraints catch any residual insert race.

An unresolved pending attempt blocks a second key. Reusing the same key:

- for the same principal/order/fingerprint returns the existing final result;
- while pending returns conflict and directs reconciliation;
- for another order/principal/input returns conflict.

## Reconciliation versus webhook

Both call the same idempotent transition and lock order then payment.

The winner changes pending to final. The loser re-reads a non-pending payment and returns without reapplying order events, stock changes, or outbox rows.

## Shipment versus cancellation/refund

Both lock the order first.

- If shipment commits first, allocations are consumed and refund cancellation is rejected as a returns case.
- If refund cancellation locks first, order becomes cancellation pending; shipment creation/ship validation rejects an order not ready for fulfillment.

Shipment then locks exact allocations/inventory before consuming physical stock.

## Worker claiming

Outbox workers use `FOR UPDATE SKIP LOCKED`. Multiple worker replicas claim different rows instead of waiting on the same batch.

Payment sweeps select due IDs and rely on per-payment locks plus idempotent transitions. A future high-volume optimization can add explicit claim leases; correctness does not depend on only one sweeper.

## Optimistic versus pessimistic techniques

The OMS uses pessimistic row locks where a short transaction protects scarce stock or a state transition. It does not use a global distributed Redis lock because:

- PostgreSQL already owns the protected state;
- a separate lock service creates split-brain and lease-expiry failure modes;
- row locks release automatically on rollback/disconnect.

Optimistic version columns can improve low-contention editing later, but do not replace atomic inventory reservation.

## Testing concurrency

Concurrency tests use distinct SQLAlchemy sessions and threads against real PostgreSQL. SQLite is not a substitute: its locking, constraints, and `FOR UPDATE` behavior differ.

Relevant tests:

- `test_payment_concurrency.py`: simultaneous orders cannot over-reserve.
- `test_order_payment_races.py`: cancellation during provider call does not corrupt inventory.
- `test_multiwarehouse_fulfillment.py`: split allocations and shipment consumption.
- payment service tests: duplicate keys, retries, pending review, and provider uncertainty.

Run:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://oms_user:local_dev_password@127.0.0.1:5432/order_management_test"
uv run pytest tests/test_payment_concurrency.py tests/test_order_payment_races.py -v
```
