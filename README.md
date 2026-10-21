# Order Management System

This repository is a learning-oriented, production-structured order management system. It combines a FastAPI modular monolith, PostgreSQL, Keycloak, RabbitMQ/Celery, Redis, interchangeable payment providers, an Angular client, Docker Compose, and Kubernetes packaging.

The backend currently contains the implemented product, customer, multi-warehouse inventory, allocation, order, payment, refund, shipment, outbox, worker, security, and observability foundations. The frontend and Kubernetes implementation continue after the backend is documented and verified.

## Start here

1. [Backend documentation index](docs/backend/README.md)
2. [Backend setup](docs/backend/setup.md)
3. [Architecture](docs/backend/architecture.md)
4. [Domain model and invariants](docs/backend/domain-model.md)
5. [Transaction and failure flows](docs/backend/transaction-flows.md)
6. [Manual backend testing](docs/backend/manual-testing.md)
7. [Design decisions](docs/backend/decisions.md)

## Repository layout

```text
backend/          FastAPI API, domain services, Celery workers, migrations, tests
frontend/         Angular application
docs/backend/     Backend learning and operations documentation
keycloak/         Local learning realm import
scripts/          Local infrastructure initialization
observability/    Prometheus and Grafana local configuration
```

## Important status statement

“Production-structured” does not mean “safe to deploy unchanged.” Production deployment still requires managed secrets, externally managed stateful services, TLS, backups, restore drills, organization-specific identity configuration, Stripe review, capacity testing, alert routing, and successful verification in the target environment. The documentation labels local-only credentials and shortcuts explicitly.
