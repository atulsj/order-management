from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sentry_sdk import init as init_sentry
from sqlalchemy import Engine

from app.core.config import Settings


def configure_telemetry(app: FastAPI, engine: Engine, settings: Settings) -> None:
    if settings.sentry_dsn is not None:
        init_sentry(
            dsn=settings.sentry_dsn.get_secret_value(),
            environment=settings.environment,
            release=settings.app_version,
            send_default_pii=False,
            traces_sample_rate=0.1,
        )
    if settings.otel_exporter_otlp_endpoint is not None:
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": "oms-api",
                    "service.version": settings.app_version,
                    "deployment.environment": settings.environment,
                }
            )
        )
        exporter = OTLPSpanExporter(
            endpoint=str(settings.otel_exporter_otlp_endpoint)
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine)
    HTTPXClientInstrumentor().instrument()
