
import os

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models import Inventory, Order, OrderItem, Payment, Product


@pytest.fixture
def db_session():
    database_url = os.getenv("TEST_DATABASE_URL")

    if not database_url:
        pytest.fail("TEST_DATABASE_URL must be configured")

    if "order_management_test" not in database_url:
        pytest.fail(
            "Refusing to run against a database other than "
            "order_management_test"
        )

    test_engine = create_engine(database_url, pool_pre_ping=True)

    try:
        Base.metadata.create_all(test_engine)

        TestingSessionLocal = sessionmaker(
            bind=test_engine,
            autoflush=False,
            expire_on_commit=False,
        )

        with TestingSessionLocal() as session:
            yield session
    finally:
        # Clean up only rows created by tests that use this fixture.
        with TestingSessionLocal() as cleanup_session:
            cleanup_session.execute(delete(Payment))
            cleanup_session.execute(delete(OrderItem))
            cleanup_session.execute(delete(Inventory))
            cleanup_session.execute(delete(Order))
            cleanup_session.execute(delete(Product))
            cleanup_session.commit()

        test_engine.dispose()
