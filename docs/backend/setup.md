# Backend setup

## 1. Prerequisites

### Recommended: Docker Compose

- Docker Engine or Docker Desktop with Compose v2
- At least 6 GB of memory available to Docker
- PowerShell 7 or a POSIX shell

Compose runs PostgreSQL, RabbitMQ, Redis, Keycloak, migration job, API, Celery worker, Celery beat, Mailpit, and optional Prometheus/Grafana.

### Native Python development

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- PostgreSQL 17
- RabbitMQ 4
- Redis 8
- Keycloak 26 if authentication is enabled

Never install backend packages with global `pip`. The repository uses `uv.lock`.

## 2. Configuration

Copy examples only when you need to override defaults:

```powershell
Copy-Item .env.example .env
Copy-Item backend/.env.example backend/.env
```

Do not commit either `.env` file. Local example passwords are intentionally non-production credentials.

Important settings:

| Variable | Meaning | Local default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy PostgreSQL URL | local `order_management` |
| `KEYCLOAK_ISSUER` | Exact JWT `iss` claim | `http://localhost:8180/realms/oms` |
| `KEYCLOAK_JWKS_URL` | Internal JWKS fetch address | issuer-derived outside Compose |
| `KEYCLOAK_AUDIENCE` | Required access-token audience | `oms-api` |
| `AUTH_DISABLED` | Debug identity headers; never production | `false` |
| `PAYMENT_PROVIDER` | `simulator` or `stripe` | `simulator` |
| `SIMULATOR_OUTCOME` | Simulator result | `SUCCEEDED` |
| `RECONCILIATION_DEADLINE_HOURS` | Automatic payment lookup deadline | `24` |
| `ORDER_RESERVATION_MINUTES` | Unpaid reservation lifetime | `30` |
| `BROKER_URL` | RabbitMQ broker | local RabbitMQ |
| `REDIS_URL` | Shared rate-limit store | local Redis |
| `RATE_LIMIT_ENABLED` | Enables mutation rate limits | `true` |
| `SMTP_HOST` | SMTP destination; absent means console adapter | unset natively |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint | unset |
| `SENTRY_DSN` | Optional Sentry DSN | unset |

`KEYCLOAK_ISSUER` and the token’s `iss` claim must match exactly. In Compose the API validates the public issuer but fetches keys from the internal `KEYCLOAK_JWKS_URL`.

## 3. Compose setup

From the repository:

```powershell
cd backend
docker compose config
docker compose up --build -d
docker compose ps
```

The `migration` service must finish successfully before API and workers start.

### What Docker creates and what the PostgreSQL script creates

There are three different layers that are easy to confuse:

| Layer | Responsibility | OMS mechanism |
|---|---|---|
| PostgreSQL server | Runs the database engine and stores database files | The `postgres:17.6` container and the `postgres_data` volume |
| Logical database | Creates a named database inside the server | `POSTGRES_DB=order_management` for the application database; `scripts/postgres/init-test-db.sql` for the separate test database |
| Application schema | Creates and evolves tables, columns, constraints, indexes, and data backfills | Alembic revisions applied by the `migration` service |

Starting the PostgreSQL Docker container does **not** automatically create the OMS
tables. On the first initialization of an empty `postgres_data` volume, the official
PostgreSQL image:

1. creates the `oms_user` role from `POSTGRES_USER`,
2. creates the `order_management` database from `POSTGRES_DB`, and
3. executes files mounted under `/docker-entrypoint-initdb.d/`.

Compose mounts
`scripts/postgres/init-test-db.sql` into that initialization directory. The script
only creates `order_management_test` and grants the local OMS user access to it. It
does not create a second PostgreSQL server, duplicate the Docker database, or create
OMS application tables. The test database is deliberately separate so a test that
deletes or rolls back data cannot damage local development data.

The top-level `scripts/postgres/` directory contains PostgreSQL-specific environment
bootstrap helpers rather than Python application code or Alembic schema history.
Keeping the script outside the image makes its purpose and Compose mount explicit.

Initialization scripts run **only when PostgreSQL initializes an empty data
directory**. They do not run on every `docker compose up`. Once the named
`postgres_data` volume exists:

- restarting or rebuilding the container preserves both databases and their data;
- editing `init-test-db.sql` does not rerun it against the existing volume;
- Alembic remains responsible for ongoing application-schema changes.

If an older local volume was created before the test script existed, create
`order_management_test` manually or intentionally perform the complete destructive
reset described in [Resetting local state](#7-resetting-local-state). Never remove a
production volume to make an initialization script rerun.

Seed two warehouses and sample products:

```powershell
docker compose exec api python -m app.seed
```

Check health:

```powershell
Invoke-RestMethod http://localhost:8000/live
Invoke-RestMethod http://localhost:8000/ready
```

Expected readiness response:

```json
{
  "status": "ready",
  "database": "connected",
  "redis": "connected"
}
```

View logs:

```powershell
docker compose logs -f api worker beat
```

Start optional observability:

```powershell
docker compose --profile observability up -d prometheus grafana
```

## 4. Native API setup

Start infrastructure only:

```powershell
cd backend
docker compose up -d postgres rabbitmq redis keycloak mailpit
```

Install locked dependencies and migrate:

```powershell
uv sync --frozen
uv run alembic upgrade head
uv run python -m app.seed
```

Run API, worker, and scheduler in separate terminals:

```powershell
uv run uvicorn app.main:app --reload --port 8000
```

```powershell
uv run celery -A app.workers.celery_app:celery_app worker --loglevel=INFO --queues=payments,notifications,maintenance
```

```powershell
uv run celery -A app.workers.celery_app:celery_app beat --loglevel=INFO
```

## 5. Database migrations

### Why Alembic is needed when PostgreSQL already exists

The PostgreSQL container supplies a running database engine. Alembic supplies
**version-controlled application schema evolution**. These are different jobs.

For example, Docker can create an empty database named `order_management`, but it
does not know that the OMS needs `orders`, `payments`, `inventory_allocations`, or
their constraints and indexes. Those details live in ordered Python revision files
under `backend/alembic/versions/`.

Alembic also handles upgrades of databases that already contain data. Replacing
Alembic with SQLAlchemy `Base.metadata.create_all()` would only create missing
tables; it would not reliably rename columns, replace constraints, backfill existing
rows, or record which transformations have already run.

### How this repository connects Alembic

- `alembic.ini` identifies the migration directory and contains Alembic logging and
  template settings.
- `alembic/env.py` imports `Base.metadata` and all models so autogeneration can see
  the declared schema.
- Online migration runs obtain `DATABASE_URL` from the same typed settings used by
  the application, then open a short-lived database connection.
- `alembic/versions/*.py` files form a linked revision chain. Each file identifies
  its own revision and its parent revision and provides `upgrade()` and
  `downgrade()` functions.
- Alembic stores the installed revision in the database's `alembic_version` table.

The revision file is not executed merely because it exists in Git. It is executed
when `alembic upgrade` determines that the database's recorded revision is behind
the requested target.

### What `upgrade head` does

Run:

```powershell
uv run alembic upgrade head
```

Alembic then:

1. reads the target database URL;
2. connects to that database;
3. reads its current revision from `alembic_version` (or treats a new database as
   having no revision);
4. follows the revision chain from the installed revision to `head`;
5. executes each missing `upgrade()` in order; and
6. records the successfully installed revision.

Running the command again is safe: if the database is already at `head`, there are
no pending revisions to apply. A failed transactional migration is rolled back where
PostgreSQL transactional DDL permits it, and the migration service exits nonzero.
API and worker containers are configured not to start after that failure, preventing
new code from operating against an incompatible schema.

In Compose, the one-shot `migration` service runs exactly this command after
PostgreSQL becomes healthy. The API, worker, and beat services depend on its
successful completion. Separating migration from API startup prevents multiple API
replicas from racing to change the schema.

### Inspect migration state

Show the revision available in the code:

```powershell
uv run alembic heads
```

Show the revision installed in the configured database:

```powershell
uv run alembic current
```

Show the complete revision chain:

```powershell
uv run alembic history
```

Generate SQL for inspection without applying it:

```powershell
uv run alembic upgrade head --sql
```

### Create a migration after changing a model

```powershell
uv run alembic revision --autogenerate -m "describe the schema change"
```

Autogenerate compares the current database schema with SQLAlchemy model metadata and
creates a **proposal**, not a guaranteed-correct migration. Always inspect and edit
the generated file. Autogenerate cannot understand business meaning, data
backfills, enum conversions, production lock duration, or rollout compatibility.
After review, apply it locally with `uv run alembic upgrade head`, run migration and
application tests, and commit the model and revision together.

Do not edit an already-applied shared revision to add a new schema change. Other
databases may have recorded the old revision as complete. Create a new child
revision instead.

### Main and test databases

Alembic always modifies the database named by `DATABASE_URL`; it does not migrate
every database in the PostgreSQL server automatically. The Compose migration service
targets `order_management`. The test database has a separate URL:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://oms_user:local_dev_password@127.0.0.1:5432/order_management_test"
```

The current application integration-test fixture creates and removes model metadata
inside that isolated test database. Migration-specific verification should instead
point `DATABASE_URL` at a disposable database and run `uv run alembic upgrade head`
so the revision chain itself is what creates the schema.

### Downgrades and rollback safety

The multi-warehouse migration is intentionally irreversible. Its downgrade raises an error because deleting allocation, shipment, audit, and warehouse data would imply unsafe data loss. Restore a verified backup for rollback.

## 6. Local identities

The imported realm supplies:

| Username | Password | Roles |
|---|---|---|
| `customer` | `customer_password` | customer |
| `operator` | `operator_password` | operator |
| `admin` | `admin_password` | admin, operator |

The Keycloak administrator is `admin` / `local_admin_password`.

These credentials exist only for local learning. Production must use separate identity provisioning, MFA/policy controls, rotated secrets, and no password-grant flow.

## 7. Resetting local state

Stopping is safe:

```powershell
docker compose down
```

`docker compose down -v` deletes all local PostgreSQL, RabbitMQ, Redis, Keycloak, and Grafana volume data. Run it only when you intentionally want a complete local reset.

## 8. Common setup failures

- **API waits for Keycloak:** inspect `docker compose logs keycloak`; first import can take time.
- **Issuer mismatch:** inspect the JWT `iss` claim and compare it byte-for-byte with `KEYCLOAK_ISSUER`.
- **Migration exits nonzero:** inspect `docker compose logs migration`; do not start API against a partially migrated schema.
- **Readiness is 503:** check PostgreSQL and Redis health. Liveness remains 200 because the process itself is alive.
- **Tests refuse database:** set `TEST_DATABASE_URL` and ensure its database name contains `order_management_test`.
- **Port conflict:** change only the host side of a Compose mapping; keep container-to-container ports unchanged.
