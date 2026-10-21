# OMS backend

The backend is a synchronous FastAPI and SQLAlchemy modular monolith. PostgreSQL is the source of truth; Keycloak supplies identities and roles; Redis supplies shared rate-limit state; RabbitMQ and Celery execute durable background work.

## Quick commands

```powershell
cd backend
uv sync --frozen
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload
```

Run supporting services and the API through Docker Compose:

```powershell
cd backend
docker compose up --build -d
docker compose exec api python -m app.seed
```

Useful endpoints:

- API docs: `http://localhost:8000/docs`
- Liveness: `http://localhost:8000/live`
- Readiness: `http://localhost:8000/ready`
- Metrics: `http://localhost:8000/metrics`
- Keycloak: `http://localhost:8180`
- RabbitMQ management: `http://localhost:15672`
- Mailpit: `http://localhost:8025`

Read the complete guides in [`../docs/backend/`](../docs/backend/README.md).
