
import logging
from collections.abc import Generator
from time import perf_counter

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout,
    pool_recycle=settings.database_pool_recycle,
    connect_args={"application_name": "oms-api"},
)

@event.listens_for(engine, "connect")
def log_new_connection(dbapi_connection, connection_record):
    logger.debug("New PostgreSQL connection established")


@event.listens_for(engine, "before_cursor_execute")
def start_query_timer(
    conn, cursor, statement, parameters, context, executemany
):
    context._query_started_at = perf_counter()


@event.listens_for(engine, "after_cursor_execute")
def log_query_duration(
    conn, cursor, statement, parameters, context, executemany
):
    elapsed_ms = (
        perf_counter() - context._query_started_at
    ) * 1000

    if elapsed_ms >= 250:
        logger.warning("Slow SQL execution took %.2f ms", elapsed_ms)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Provide a database session and always close it afterward."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
