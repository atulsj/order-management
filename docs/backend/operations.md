# Backend operations

## Health semantics

- `/live`: process is running; never checks remote dependencies.
- `/ready`: PostgreSQL and Redis are reachable; a failing instance should leave load-balancer rotation.
- `/metrics`: Prometheus exposition.
- `/health`: compatibility alias for liveness.

Do not restart every replica merely because a shared database is briefly unavailable; that can amplify an outage. Readiness should remove traffic while liveness remains healthy.

## Structured logs

Each HTTP response receives `X-Request-ID`. Logs include request ID, method, route, status, and duration. JSON is default in containers.

Never log:

- bearer tokens or cookies,
- Stripe client/secret/webhook values,
- full webhook/card data,
- address/phone/email PII,
- database/broker credentials.

Use safe numeric domain IDs and a one-way subject hash where identity correlation is needed.

## Metrics and alerts

Current generic Python/process metrics are exposed. Production dashboards should add/alert on:

- HTTP request rate, 4xx/5xx, p50/p95/p99;
- DB pool checked-out/wait/timeout and slow-query count;
- Rabbit queue depth, unacknowledged tasks, worker heartbeat;
- payment review count and oldest review age;
- reconciliation deadline breaches;
- refund review count;
- unpublished/dead-letter outbox count and age;
- reservation expiry count;
- inventory conflict count;
- webhook invalid signature and duplicate count.

Suggested page conditions:

- any reconciliation deadline breach older than operator SLA;
- dead-letter outbox > 0;
- readiness failures across all API replicas;
- sustained 5xx rate;
- database pool wait near timeout;
- payment queue age increasing;
- broker/worker unavailable.

## Tracing

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to export FastAPI, SQLAlchemy, HTTPX, and Celery traces. Propagate request/trace context through tasks when adding custom messages.

Do not attach PII, tokens, raw SQL parameters, or payment secrets to spans.

## Scaling and connection budgeting

Every API process has:

```text
pool capacity = DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW
```

Total possible connections roughly equal:

```text
API replicas × API process count × API pool capacity
+ worker processes × worker pool capacity
+ migrations/operations
+ safety reserve
```

Keep this below managed PostgreSQL limits. More application replicas without connection budgeting can reduce availability.

Scale API on measured request concurrency/latency and worker groups on queue age, not CPU alone.

Use separate worker deployments/queues for payments and notifications in Kubernetes so slow email does not delay money workflows.

## Migrations and deployment

1. Back up database and verify restore path.
2. Test migration on representative copy.
3. Deploy backward-compatible expand migration.
4. Run one controlled migration job.
5. Deploy code.
6. Verify readiness, smoke flow, review/outbox counts.
7. Contract/drop old schema only in a later deployment.

Never let every API replica run migrations at startup.

The current large multi-warehouse migration is appropriate for learning/small datasets. For large production tables, split into expand/backfill/validate/contract releases and batch backfills to control locks.

## Backup and restore

Production PostgreSQL should use managed automated backups plus point-in-time recovery. RabbitMQ is delivery infrastructure, not the business source of truth; PostgreSQL outbox rows allow replay.

Logical local backup:

```powershell
docker compose exec postgres pg_dump `
    -U oms_user `
    -Fc `
    -d order_management `
    -f /tmp/oms.dump
docker compose cp postgres:/tmp/oms.dump ./oms.dump
```

Restore drills must verify:

- row counts;
- inventory arithmetic constraints;
- active allocations equal reserved quantities;
- payment/refund attempt history;
- outbox replay;
- migration version;
- application smoke flow.

Do not run restore commands against an existing production database without an approved disaster-recovery procedure.

## Secrets

Compose credentials are local examples. Kubernetes/production should reference external secret management.

Rotate independently:

- PostgreSQL credentials;
- RabbitMQ credentials;
- Redis credentials;
- Keycloak client/admin secrets;
- Stripe API and webhook secrets;
- SMTP credentials;
- Sentry/OTLP credentials.

Rotation should support overlap where providers allow it. Never bake secrets into images or Helm values committed to Git.

## Security controls

- Keycloak JWT signature/issuer/audience/expiry validation.
- Role and object-ownership checks.
- Strict allowed origins/hosts.
- mutation rate limits and request body limit.
- non-root backend image.
- parameterized SQLAlchemy queries.
- raw-body Stripe signature verification.
- PII minimization.

Before production add organization-specific ingress TLS, WAF/DDoS controls, dependency/image/SBOM scanning, network policies, secret store, database TLS, audit retention, privacy retention/deletion, and penetration testing.

## Queue recovery

Celery tasks are late-acknowledged and reject on worker loss. Tasks must be safe to redeliver.

If workers are down:

- API domain commits can continue until business policy says stop;
- outbox rows accumulate safely in PostgreSQL;
- payment reconciliation age rises;
- reservations remain protected;
- alerts must fire before SLA/deadline breach.

After recovery, scale payment workers carefully and monitor provider/database rate limits.

## Known current limitations

- Catalog/order/payment lists use offset pagination.
- Shipment can select subsets of allocation rows but cannot split one allocation row across several shipments.
- Returns/exchanges, tax, promotions, carrier rates, and multi-currency minor units are not implemented.
- Redis rate limiting currently fails open on Redis command failure while readiness fails.
- Local Compose is single-instance stateful infrastructure.
- Full PostgreSQL/Compose/migration verification has not yet run in the current machine environment.
