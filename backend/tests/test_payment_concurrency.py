
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import Inventory, Product
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services.order_service import create_order


def test_concurrent_orders_cannot_over_reserve_inventory(db_session):
    """
    Stock is 10. Two simultaneous orders each request 6.
    Exactly one should succeed, leaving 6 reserved and 4 available.
    """
    product = Product(
        sku="CONCURRENCY-001",
        name="Concurrency test product",
        price=Decimal("100.00"),
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    inventory = Inventory(
        product_id=product.id,
        quantity_on_hand=10,
        quantity_reserved=0,
    )
    db_session.add(inventory)
    db_session.commit()

    product_id = product.id
    engine = db_session.get_bind()
    TestSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    barrier = Barrier(2)

    def place_order():
        with TestSession() as session:
            barrier.wait(timeout=10)
            try:
                order = create_order(
                    session,
                    OrderCreate(
                        items=[
                            OrderItemCreate(
                                product_id=product_id,
                                quantity=6,
                            )
                        ]
                    ),
                )
                return ("success", order.id)
            except HTTPException as exc:
                session.rollback()
                return ("rejected", exc.status_code)
            except Exception:
                session.rollback()
                raise

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(place_order),
            executor.submit(place_order),
        ]
        results = [future.result(timeout=30) for future in futures]

    assert sum(result[0] == "success" for result in results) == 1
    assert sum(result[0] == "rejected" for result in results) == 1

    db_session.expire_all()
    inventory = db_session.scalar(
        select(Inventory).where(Inventory.product_id == product_id)
    )

    assert inventory.quantity_on_hand == 10
    assert inventory.quantity_reserved == 6
    assert inventory.quantity_reserved <= inventory.quantity_on_hand
