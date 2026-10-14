
import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
import logging
from time import perf_counter

from sqlalchemy import event

logger = logging.getLogger(__name__)



DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://oms_user:local_dev_password@127.0.0.1:5432/order_management",
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

@event.listens_for(engine, "connect")
def log_new_connection(dbapi_connection, connection_record):
    logger.info("New PostgreSQL connection established")


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

    logger.info("SQL execution took %.2f ms", elapsed_ms)

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
