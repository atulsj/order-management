# Backend documentation

This documentation explains both how to run the backend and why it is designed this way. Read it in order the first time.

| Document | Purpose |
|---|---|
| [Setup](setup.md) | Prerequisites, Compose and native setup, migrations, seed data, configuration |
| [Architecture](architecture.md) | Components, boundaries, synchronous and asynchronous interactions |
| [Domain model](domain-model.md) | Entities, state machines, inventory arithmetic, business invariants |
| [Transaction flows](transaction-flows.md) | Exact operation order, commit boundaries, crash recovery |
| [Concurrency](concurrency.md) | Row locks, lock ordering, races, idempotency, deadlock handling |
| [Payments and failures](payments-and-failures.md) | Provider contract, Stripe/simulator behavior, reconciliation, refunds |
| [Manual testing](manual-testing.md) | PowerShell API walkthrough and failure scenarios |
| [API reference](api-reference.md) | Endpoint roles, request purpose, idempotency, and status behavior |
| [Automated testing](automated-testing.md) | Test database, test suites, static checks, coverage |
| [File reference](file-reference.md) | Responsibility of every backend source/configuration group |
| [Design decisions](decisions.md) | Chosen and rejected alternatives with consequences |
| [Security model](security.md) | Trust boundaries, threats, implemented controls, production gaps |
| [Operations](operations.md) | Health, metrics, logs, scaling, migrations, backup and restore |
| [Payment review runbook](runbooks/payment-review.md) | Investigating uncertain payments and deadline breaches |
| [Inventory runbook](runbooks/inventory-inconsistency.md) | Diagnosing reservation and stock inconsistencies |

## Learning path

1. Run the stack with [Setup](setup.md).
2. Follow one order using [Manual testing](manual-testing.md).
3. Read the diagrams in [Architecture](architecture.md).
4. Study [Transaction flows](transaction-flows.md) and [Concurrency](concurrency.md) together.
5. Trigger provider failures and compare database state with [Payments and failures](payments-and-failures.md).
6. Read [Design decisions](decisions.md) before changing architectural boundaries.

## Documentation accuracy

The documents describe the code in the current working tree. Features not yet fully verified are called out. The backend’s Ruff and Pyright checks and database-independent tests have run successfully. PostgreSQL integration, Compose, and migration execution still need Docker or an accessible PostgreSQL test database in the current environment.
