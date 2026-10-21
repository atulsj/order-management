# Backend design decisions

Each decision records the problem, choice, alternatives not chosen, and consequence. These are not universal rules; they fit this OMS’s current scale and learning goals.

## 1. Modular monolith before microservices

**Chosen:** one FastAPI domain codebase and PostgreSQL schema, deployed as API and worker process types.

**Not chosen:** separate catalog, inventory, order, payment, and fulfillment services.

**Why:** inventory/order/payment invariants need atomic local transactions. Early service boundaries would add distributed transactions, event versioning, network failure, deployment overhead, and debugging complexity before scale proves the need.

**Consequence:** modules need discipline to avoid a “big ball of mud.” Outbox events create future extraction seams.

## 2. Synchronous SQLAlchemy

**Chosen:** synchronous SQLAlchemy sessions and regular FastAPI handlers.

**Not chosen:** rewrite to async SQLAlchemy/asyncpg.

**Why:** current services are synchronous, PostgreSQL is the main workload, FastAPI runs regular handlers in a threadpool, and correctness work has higher value than an async rewrite.

**Consequence:** size threadpool and DB pool together; never call blocking services from `async def` without offloading.

## 3. PostgreSQL is the consistency boundary

**Chosen:** row locks, constraints, and transactions in the database that stores stock.

**Not chosen:** Redis distributed locks or in-memory mutexes.

**Why:** separate locks can expire or split-brain while PostgreSQL state remains authoritative. Database locks release on rollback/disconnect.

**Consequence:** transactions must be short and lock order documented.

## 4. Explicit warehouse allocations

**Chosen:** an order item owns exact allocation rows against warehouse inventory.

**Not chosen:** reserve only an aggregate product quantity and choose warehouse during shipment.

**Why:** explicit allocations explain which location promised stock, support split fulfillment, make cancellation exact, and prevent later allocation ambiguity.

**Consequence:** rebalancing allocations requires an explicit future operation.

## 5. Deterministic priority allocation

**Chosen:** warehouse priority, then IDs, taking available quantity until satisfied.

**Not chosen:** nearest warehouse optimization, cost-based routing, or random balancing.

**Why:** deterministic behavior is explainable, testable, and deadlock-friendly.

**Consequence:** geography/carrier/capacity optimization is a future strategy interface, not currently claimed.

## 6. Physical stock leaves on shipment

**Chosen:** payment success confirms; shipment decreases on-hand and reserved.

**Not chosen:** decrease on-hand when payment succeeds.

**Why:** `quantity_on_hand` models physical warehouse stock. Paid goods can remain physically present, and a paid cancellation must release rather than invent stock.

**Consequence:** available stock is reduced at checkout through reserved quantity.

## 7. Keycloak rather than local passwords

**Chosen:** external OIDC provider, RS256/JWKS validation, PKCE SPA flow.

**Not chosen:** build password hashing, reset, MFA, sessions, and account security inside OMS.

**Why:** identity security is specialized and should be delegated.

**Consequence:** Keycloak availability/configuration is operationally required; OMS still enforces ownership and roles.

## 8. Customer profile keyed by subject

**Chosen:** immutable Keycloak `sub`.

**Not chosen:** email as foreign identity key.

**Why:** email changes and can be recycled; subject is the stable identity identifier.

## 9. Durable Celery/RabbitMQ work

**Chosen:** RabbitMQ broker and Celery worker/beat.

**Not chosen:** FastAPI `BackgroundTasks`, in-process scheduler, or Redis-only queue.

**Why:** payment reconciliation and outbox work must survive API restarts and support acknowledgements/retries.

**Consequence:** tasks must be idempotent because delivery is at least once.

## 10. Transactional outbox, not database-plus-broker dual write

**Chosen:** domain row and outbox row in one commit; dispatcher publishes later.

**Not chosen:** commit domain then directly publish, or publish then commit.

**Why:** either dual-write ordering has a crash window that loses truth.

**Consequence:** duplicate publication is possible; consumers deduplicate or perform idempotent operations.

## 11. No distributed two-phase commit with payment provider

**Chosen:** durable local intent, provider idempotency, reconciliation.

**Not chosen:** hold DB transaction around network call or attempt 2PC.

**Why:** Stripe does not participate in PostgreSQL transactions; long DB locks do not make external side effects atomic.

## 12. Uncertain is a first-class payment state

**Chosen:** database status stays pending plus review metadata.

**Not chosen:** timeout becomes failure.

**Why:** timeout cannot prove no charge. False failure enables double charge.

## 13. Separate client and provider idempotency keys

**Chosen:** caller key is bound to principal/request; provider key is generated per attempt.

**Not chosen:** forward client key directly.

**Why:** separates security/contract boundaries and lets retries create distinct attempts while reconciling one provider operation.

## 14. Webhook inbox

**Chosen:** persist unique provider event ID before applying.

**Not chosen:** trust webhook delivery once.

**Why:** providers retry and can deliver duplicates/out of order.

## 15. Refund before releasing paid reservation

**Chosen:** paid cancellation releases only after definitive refund success.

**Not chosen:** cancel/release immediately and hope refund succeeds.

**Why:** failed refund would leave confirmed money without reserved goods.

**Consequence:** cancellation pending can hold stock during provider uncertainty.

## 16. Offset pagination now, keyset later for largest queues

**Chosen:** bounded `limit`/`offset` with stable ordering for current APIs.

**Not chosen yet:** cursor/keyset for every list.

**Why:** simpler learning/API client behavior at current data scale.

**Consequence:** deep offsets become expensive; order/payment operational queues should move to keyset when measurements justify.

## 17. Redis for rate counters, not business state

**Chosen:** shared mutation limits keyed by a hash of identity/path/window.

**Not chosen:** per-process counters.

**Why:** replicas need a shared counter.

**Consequence:** current middleware fails open if Redis is unavailable but readiness reports dependency failure. Environments with strict abuse requirements may choose fail closed for selected endpoints.

## 18. Native PostgreSQL decimal amounts

**Chosen:** `NUMERIC(12,2)` and Python `Decimal`.

**Not chosen:** binary floating point.

**Why:** floating point cannot exactly represent common monetary decimals.

**Limit:** current system is configured for one three-letter currency and assumes two minor units in Stripe conversion. Zero/three-decimal currencies require explicit currency metadata support.

## 19. No tax, promotions, carrier rating, or returns yet

**Chosen:** document extension points and refuse unsupported transitions.

**Not chosen:** fake flat tax, simplistic coupon logic, or treating returns as cancellations.

**Why:** these are separate complex domains with jurisdiction/provider policies. Incorrect simplification is worse than an explicit boundary.

## 20. Audit timeline, not event sourcing/CQRS

**Chosen:** current-state rows plus append-only operational events.

**Not chosen:** rebuild every aggregate from event streams.

**Why:** event sourcing adds schema evolution, projection, replay, and consistency complexity not justified here.

## 21. Irreversible data migration

**Chosen:** multi-warehouse migration refuses destructive downgrade.

**Not chosen:** a downgrade that discards allocations/shipments/new audit data.

**Why:** rollback safety requires backup restore and compatible rollout, not hidden data loss.

## 22. Helm as deployment source, raw YAML as learning output

**Chosen:** one configurable Helm chart and `helm template` teaching.

**Not chosen:** separately maintained raw and Helm manifests.

**Why:** duplicated manifests drift. Rendered Helm output is still ordinary Kubernetes YAML and exposes every primitive.
