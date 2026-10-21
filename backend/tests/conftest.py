
import os

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models import (
    Customer,
    CustomerAddress,
    Inventory,
    InventoryAllocation,
    Order,
    OrderAddress,
    OrderEvent,
    OrderItem,
    OutboxEvent,
    Payment,
    Product,
    Refund,
    Shipment,
    ShipmentItem,
    SimulatorTransaction,
    StockMovement,
    Warehouse,
    WebhookInbox,
)


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
    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    try:
        Base.metadata.create_all(test_engine)

        with TestingSessionLocal() as session:
            if session.get(Warehouse, 1) is None:
                session.add(
                    Warehouse(
                        id=1,
                        code="DEFAULT",
                        name="Default Warehouse",
                        priority=100,
                    )
                )
                session.commit()
            yield session
    finally:
        # Clean up only rows created by tests that use this fixture.
        with TestingSessionLocal() as cleanup_session:
            cleanup_session.execute(delete(ShipmentItem))
            cleanup_session.execute(delete(Shipment))
            cleanup_session.execute(delete(Refund))
            cleanup_session.execute(delete(Payment))
            cleanup_session.execute(delete(WebhookInbox))
            cleanup_session.execute(delete(SimulatorTransaction))
            cleanup_session.execute(delete(OutboxEvent))
            cleanup_session.execute(delete(OrderEvent))
            cleanup_session.execute(delete(OrderAddress))
            cleanup_session.execute(delete(InventoryAllocation))
            cleanup_session.execute(delete(OrderItem))
            cleanup_session.execute(delete(StockMovement))
            cleanup_session.execute(delete(Inventory))
            cleanup_session.execute(delete(Order))
            cleanup_session.execute(delete(CustomerAddress))
            cleanup_session.execute(delete(Customer))
            cleanup_session.execute(delete(Product))
            cleanup_session.execute(delete(Warehouse))
            cleanup_session.commit()

        test_engine.dispose()
