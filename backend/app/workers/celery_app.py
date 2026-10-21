from celery import Celery
from opentelemetry.instrumentation.celery import CeleryInstrumentor

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "oms",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=270,
    broker_connection_retry_on_startup=True,
    task_default_queue="maintenance",
    task_routes={
        "app.workers.tasks.reconcile_payments": {"queue": "payments"},
        "app.workers.tasks.reconcile_refunds": {"queue": "payments"},
        "app.workers.tasks.process_domain_event": {"queue": "notifications"},
    },
    beat_schedule={
        "dispatch-outbox-every-five-seconds": {
            "task": "app.workers.tasks.dispatch_outbox",
            "schedule": 5.0,
        },
        "reconcile-payments-every-minute": {
            "task": "app.workers.tasks.reconcile_payments",
            "schedule": 60.0,
        },
        "reconcile-refunds-every-minute": {
            "task": "app.workers.tasks.reconcile_refunds",
            "schedule": 60.0,
        },
        "expire-orders-every-minute": {
            "task": "app.workers.tasks.expire_orders",
            "schedule": 60.0,
        },
    },
    timezone="UTC",
)
CeleryInstrumentor().instrument()
