# Backend API reference

Interactive, schema-accurate OpenAPI is available at `/docs`. This page explains authorization and business intent.

All application resources are under `/api/v1`. Errors use `application/problem+json` with title, status, detail, instance, and request ID.

## Health and operations

| Method/path | Auth | Purpose |
|---|---|---|
| `GET /live` | none | process liveness |
| `GET /ready` | none | PostgreSQL/Redis readiness |
| `GET /metrics` | network-restricted in production | Prometheus metrics |
| `GET /docs` | restrict in production as policy requires | OpenAPI UI |

## Products

| Method/path | Role | Purpose |
|---|---|---|
| `GET /api/v1/products` | public | active catalog search and bounded pagination |
| `GET /api/v1/products/{product_id}` | public | product detail |
| `POST /api/v1/products` | admin | create product |
| `PATCH /api/v1/products/{product_id}` | admin | update fields |
| `DELETE /api/v1/products/{product_id}` | admin | soft-deactivate |

Catalog list includes aggregate available quantity across warehouses.

## Warehouses and inventory

| Method/path | Role | Purpose |
|---|---|---|
| `GET /api/v1/warehouses` | operator/admin | priority-ordered locations |
| `POST /api/v1/warehouses` | admin | create location |
| `PATCH /api/v1/warehouses/{id}` | admin | rename/reprioritize/activate |
| `GET /api/v1/inventory` | operator/admin | filter by warehouse/product |
| `GET /api/v1/inventory/products/{product_id}` | public | product inventory for specified/default warehouse |
| `POST /api/v1/inventory` | admin | create warehouse/product inventory |
| `POST /api/v1/inventory/{product_id}/receive` | operator/admin | receive positive stock |
| `POST /api/v1/inventory/{inventory_id}/adjust` | admin | reason-coded signed adjustment |
| `GET /api/v1/inventory/{inventory_id}/movements` | operator/admin | physical ledger |
| `GET /api/v1/inventory/alerts/low-stock` | operator/admin | availability threshold |

Receiving/adjusting uses row locks and writes a movement. Adjustment cannot reduce on-hand below reserved.

## Customer profile

| Method/path | Role | Purpose |
|---|---|---|
| `GET /api/v1/me` | authenticated | synchronized profile and owned addresses |
| `POST /api/v1/me/addresses` | authenticated | save address |
| `DELETE /api/v1/me/addresses/{id}` | owner | delete saved address |

Orders retain a snapshot after saved address deletion.

## Orders

| Method/path | Role | Purpose |
|---|---|---|
| `POST /api/v1/orders` | authenticated customer | checkout and allocate |
| `GET /api/v1/orders` | customer own; operator/admin all | filter/paginate |
| `GET /api/v1/orders/{id}` | customer own; operator/admin all | detail/timeline/allocations |
| `POST /api/v1/orders/{id}/cancel` | customer own; operator/admin all | unpaid release or paid refund |

Cancellation requires `Idempotency-Key`. Unpaid cancellation ignores provider workflow; paid unshipped cancellation creates an idempotent refund. Shipped order returns 409.

## Payments

| Method/path | Role | Purpose |
|---|---|---|
| `GET /api/v1/payments/configuration` | public | provider name, publishable key, currency |
| `POST /api/v1/payments` | customer own order; operator/admin | create attempt |
| `GET /api/v1/payments` | customer own; operator/admin all | paginated attempts/review filter |
| `POST /api/v1/payments/reconcile` | operator/admin | trigger due sweep |
| `POST /api/v1/payments/webhooks/stripe` | Stripe signature | provider events |

Payment create requires `Idempotency-Key`. HTTP 502 means outcome is uncertain, not definitively failed. Read payment/order state rather than blindly retrying.

## Shipments

| Method/path | Role | Purpose |
|---|---|---|
| `GET /api/v1/shipments` | operator/admin | list/filter by order |
| `POST /api/v1/shipments` | operator/admin | create one-warehouse shipment from allocations |
| `PATCH /api/v1/shipments/{id}` | operator/admin | edit pending carrier/tracking |
| `POST /api/v1/shipments/{id}/ship` | operator/admin | consume allocations/physical stock |
| `POST /api/v1/shipments/{id}/deliver` | operator/admin | record delivery |

## Common statuses

- `200`: read/update/action completed.
- `201`: resource created.
- `202`: reconciliation accepted/completed as a sweep request.
- `204`: successful deletion with no body.
- `400`: malformed/signature-invalid request.
- `401`: missing/invalid/expired token.
- `403`: valid identity lacks role.
- `404`: missing or not-owned resource.
- `409`: domain state, stock, idempotency, or race conflict.
- `413`: request body over configured limit.
- `422`: schema validation failure.
- `429`: shared mutation rate limit.
- `502`: external provider outcome uncertain.
- `503`: required dependency unavailable.

## Pagination

Current list endpoints use bounded `limit` and `offset`, stable ordering, and total count. Clients must not request unbounded lists. Deep operational queues are candidates for future keyset cursors.
