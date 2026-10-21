# Automated backend testing

## Test layers

| Layer | Purpose | Database |
|---|---|---|
| Static checks | formatting, correctness smells, type analysis | none |
| Unit | settings, deadline math, normalized transitions | none or test doubles |
| Service integration | real constraints, transactions, locks | PostgreSQL |
| API integration | validation, auth, ownership, HTTP errors | PostgreSQL |
| Concurrency/race | competing sessions and threads | PostgreSQL |
| Provider contract | simulator state and mocked Stripe | PostgreSQL/test doubles |
| Migration | empty and previous schema upgrades | PostgreSQL |
| Load | latency, errors, query/pool pressure | isolated environment |

SQLite is not used for order/inventory correctness tests because it does not reproduce PostgreSQL row locking, enums, constraint behavior, or concurrency.

## Start test database

The Compose initialization script creates `order_management_test` on a fresh PostgreSQL volume.

```powershell
cd backend
docker compose up -d postgres
$env:TEST_DATABASE_URL = "postgresql+psycopg://oms_user:local_dev_password@127.0.0.1:5432/order_management_test"
```

The fixture refuses any URL not containing `order_management_test` to reduce accidental destructive cleanup.

## Run checks

```powershell
uv sync --frozen
uv run ruff check app tests
uv run pyright app
uv run pytest
```

Focused:

```powershell
uv run pytest tests/test_multiwarehouse_fulfillment.py -v
uv run pytest tests/test_payment_service.py -v
uv run pytest tests/test_payment_reconcilliation.py -v
uv run pytest tests/test_order_payment_races.py tests/test_payment_concurrency.py -v
uv run pytest tests/test_refund_service.py -v
```

Database-independent smoke tests:

```powershell
uv run pytest --no-cov tests/test_health.py tests/test_reconciliation_deadline.py
```

## Existing test responsibilities

- `conftest.py`: guarded PostgreSQL session, schema creation, default warehouse, dependency-ordered cleanup.
- `test_database_fixture.py`: proves tests target `order_management_test`.
- `test_health.py`: process liveness contract.
- `test_multiwarehouse_fulfillment.py`: deterministic split and physical stock consumption at shipment.
- `test_order_payment_races.py`: provider/cancellation race safety.
- `test_payment_concurrency.py`: simultaneous checkouts cannot over-reserve.
- `test_payment_provider_manual.py`: simulator shared-state idempotency.
- `test_payment_reconcilliation.py`: success, unknown, and not-yet-due reconciliation.
- `test_payment_service.py`: attempts, retries, provider outcomes, idempotency, review, inventory preservation.
- `test_reconciliation_deadline.py`: overdue uncertainty escalates and stops scheduling.
- `test_refund_service.py`: paid unshipped cancellation refunds and releases.

## Writing a transaction test

1. Arrange products, warehouses, and inventory through ORM or services.
2. Commit setup before invoking the service under test.
3. Invoke one public service transaction.
4. Expire/reload ORM state before assertions.
5. Assert all related rows: order/payment/allocation/inventory/event, not only the response.
6. For rollback tests, assert no partial rows remain.

## Writing a concurrency test

1. Use one shared real PostgreSQL engine.
2. Create one session per thread.
3. Synchronize start with `Barrier` or provider progress with `Event`.
4. Never share a SQLAlchemy session across threads.
5. Capture expected HTTP conflicts separately from unexpected exceptions.
6. Reload final state from a fresh/expired session.
7. Assert invariants rather than relying on which request won.

## Migration verification

At minimum test:

```powershell
uv run alembic heads
uv run alembic upgrade head
```

Production migration rehearsal must additionally:

1. restore a representative previous-version backup into an isolated database;
2. record baseline row counts and reservation sums;
3. run upgrade;
4. confirm one default warehouse exists;
5. confirm inventory moved to warehouse 1;
6. confirm pending order allocations equal prior reservations;
7. run application smoke tests;
8. measure migration lock duration.

The multi-warehouse migration has no destructive downgrade. Rollback means application compatibility plus database restore, not `alembic downgrade`.

## Coverage

`pyproject.toml` enables branch coverage and a 70% threshold. Coverage is a signal, not a correctness proof. Concurrency invariants, error branches, and migration behavior matter more than increasing a number with shallow tests.

## Load tests

Locust is a development dependency. Load tests must use an isolated environment and seeded data, never shared development or production.

Representative scenarios should cover:

- public catalog list/search;
- concurrent checkout allocation;
- payment initiation with unique keys;
- operator order/payment lists;
- shipment transitions.

Record data volume, API/worker replica count, pool settings, concurrency, p50/p95/p99 latency, error rate, outbox lag, PostgreSQL CPU/locks, and query plans.
