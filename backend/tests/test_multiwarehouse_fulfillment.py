from decimal import Decimal

from app.models import Inventory, Product, Warehouse
from app.schemas.order import OrderCreate, OrderItemCreate
from app.schemas.shipment import ShipmentCreate
from app.services.order_service import confirm_order, create_order
from app.services.shipment_service import create_shipment, mark_shipped


def test_order_splits_allocation_and_shipment_consumes_physical_stock(db_session):
    second = Warehouse(code="SECOND", name="Second Warehouse", priority=200)
    product = Product(
        sku="MULTI-001",
        name="Multi warehouse product",
        price=Decimal("25.00"),
        is_active=True,
    )
    db_session.add_all([second, product])
    db_session.commit()
    db_session.refresh(second)
    db_session.refresh(product)
    first_stock = Inventory(
        warehouse_id=1,
        product_id=product.id,
        quantity_on_hand=2,
        quantity_reserved=0,
    )
    second_stock = Inventory(
        warehouse_id=second.id,
        product_id=product.id,
        quantity_on_hand=4,
        quantity_reserved=0,
    )
    db_session.add_all([first_stock, second_stock])
    db_session.commit()

    order = create_order(
        db_session,
        OrderCreate(items=[OrderItemCreate(product_id=product.id, quantity=5)]),
    )

    assert [allocation.quantity for allocation in order.items[0].allocations] == [2, 3]
    db_session.refresh(first_stock)
    db_session.refresh(second_stock)
    assert (first_stock.quantity_on_hand, first_stock.quantity_reserved) == (2, 2)
    assert (second_stock.quantity_on_hand, second_stock.quantity_reserved) == (4, 3)

    confirm_order(db_session, order.id)
    first_allocation = order.items[0].allocations[0]
    shipment = create_shipment(
        db_session,
        ShipmentCreate(order_id=order.id, allocation_ids=[first_allocation.id]),
        "operator-test",
    )
    mark_shipped(db_session, shipment.id, "operator-test")

    db_session.refresh(first_stock)
    db_session.refresh(second_stock)
    assert (first_stock.quantity_on_hand, first_stock.quantity_reserved) == (0, 0)
    assert (second_stock.quantity_on_hand, second_stock.quantity_reserved) == (4, 3)
