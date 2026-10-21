# Runbook: inventory or reservation inconsistency

## Trigger

- database check constraint failure;
- payment/shipment/cancellation reports reservation inconsistency;
- `quantity_reserved > quantity_on_hand`;
- aggregate active allocation quantity does not equal reserved;
- missing inventory row for an allocation.

## Immediate actions

1. Stop fulfillment for affected product/warehouse.
2. Preserve logs/request IDs and current rows.
3. Do not “fix” by directly zeroing reserved quantity.
4. Identify affected inventory ID, product, warehouse, orders, allocations, and shipments.

## Read-only diagnosis

For one inventory row:

```sql
SELECT id, warehouse_id, product_id, quantity_on_hand, quantity_reserved
FROM inventory
WHERE id = :inventory_id;

SELECT status, SUM(quantity) AS quantity
FROM inventory_allocations
WHERE inventory_id = :inventory_id
GROUP BY status;

SELECT *
FROM stock_movements
WHERE inventory_id = :inventory_id
ORDER BY created_at, id;
```

Expected:

```text
inventory.quantity_reserved
= SUM(allocation.quantity WHERE allocation.status = 'RESERVED')
```

Review pending shipment rows and all order events before deciding correction.

## Likely causes

- manual database edit;
- migration/backfill inconsistency;
- untested code path changed allocation without inventory;
- duplicate external warehouse feed not idempotent;
- new code violated lock order/transaction boundary;
- restore captured inconsistent external-system point in time.

## Correction

Use an approved, reason-coded inventory adjustment or dedicated repair migration after identifying ground truth. Record actor, incident ID, before/after quantities, and affected orders.

If physical count is lower than reservations, business operations must decide allocation/customer impact; application code cannot invent stock.

## Validate

- database constraints hold;
- reserved equals active allocation sum;
- no allocation is both consumed and attached to pending shipment incorrectly;
- stock movement ledger explains physical correction;
- concurrency and incident regression test is added.
