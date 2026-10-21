from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models.allocation import InventoryAllocation
from app.models.customer import Customer, CustomerAddress
from app.models.integration_event import OutboxEvent
from app.models.inventory import Inventory
from app.models.order import Order
from app.models.order_event import OrderAddress, OrderEvent
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.warehouse import Warehouse
from app.schemas.order import OrderCreate


def _order_query():
    return select(Order).options(
        selectinload(Order.items)
        .selectinload(OrderItem.allocations)
        .selectinload(InventoryAllocation.inventory),
        selectinload(Order.shipping_address),
        selectinload(Order.events),
        selectinload(Order.shipments),
    )


def create_order(
    db: Session,
    data: OrderCreate,
    customer: Customer | None = None,
    actor_subject: str | None = None,
) -> Order:
    requested: dict[int, int] = {}
    for item in data.items:
        requested[item.product_id] = requested.get(item.product_id, 0) + item.quantity
    product_ids = sorted(requested)

    try:
        products = db.scalars(
            select(Product)
            .where(Product.id.in_(product_ids))
            .order_by(Product.id)
            .with_for_update()
        ).all()
        product_by_id = {product.id: product for product in products}
        if len(product_by_id) != len(product_ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "One or more products were not found.")
        inactive = [product.id for product in products if not product.is_active]
        if inactive:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Products are inactive: {inactive}"
            )

        inventory_rows = db.scalars(
            select(Inventory)
            .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
            .where(
                Inventory.product_id.in_(product_ids),
                Warehouse.is_active.is_(True),
            )
            .order_by(
                Inventory.product_id,
                Warehouse.priority,
                Inventory.warehouse_id,
                Inventory.id,
            )
            .with_for_update()
        ).all()
        inventory_by_product: dict[int, list[Inventory]] = {
            product_id: [] for product_id in product_ids
        }
        for inventory in inventory_rows:
            inventory_by_product[inventory.product_id].append(inventory)

        allocation_plan: dict[int, list[tuple[Inventory, int]]] = {}
        for product_id, quantity in requested.items():
            remaining = quantity
            allocations: list[tuple[Inventory, int]] = []
            for inventory in inventory_by_product[product_id]:
                available = inventory.quantity_on_hand - inventory.quantity_reserved
                allocated = min(available, remaining)
                if allocated > 0:
                    allocations.append((inventory, allocated))
                    remaining -= allocated
                if remaining == 0:
                    break
            if remaining:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Insufficient stock for product {product_id}.",
                )
            allocation_plan[product_id] = allocations

        order = Order(
            customer=customer,
            status="PENDING_PAYMENT",
            currency=get_settings().payment_currency,
            total_amount=Decimal("0.00"),
        )
        for product_id in product_ids:
            product = product_by_id[product_id]
            item = OrderItem(
                product_id=product_id,
                quantity=requested[product_id],
                unit_price=product.price,
            )
            order.items.append(item)
            order.total_amount += product.price * requested[product_id]
            for inventory, quantity in allocation_plan[product_id]:
                inventory.quantity_reserved += quantity
                item.allocations.append(
                    InventoryAllocation(
                        inventory=inventory,
                        quantity=quantity,
                        status="RESERVED",
                    )
                )

        address_data = _resolve_address(db, data, customer)
        if address_data is not None:
            order.shipping_address = OrderAddress(**address_data)
        order.events.append(
            OrderEvent(
                event_type="ORDER_CREATED",
                actor_subject=actor_subject,
                data={"total": str(order.total_amount), "currency": order.currency},
            )
        )
        db.add(order)
        db.flush()
        db.add(
            OutboxEvent(
                event_type="order.created",
                aggregate_type="order",
                aggregate_id=str(order.id),
                payload={"order_id": order.id},
                attempts=0,
            )
        )
        db.commit()
        return get_order(db, order.id)
    except Exception:
        db.rollback()
        raise


def _resolve_address(
    db: Session, data: OrderCreate, customer: Customer | None
) -> dict | None:
    if data.address_id is not None:
        if customer is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Customer is required")
        address = db.scalar(
            select(CustomerAddress).where(
                CustomerAddress.id == data.address_id,
                CustomerAddress.customer_id == customer.id,
            )
        )
        if address is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Address not found")
        return {
            "recipient_name": address.recipient_name,
            "line1": address.line1,
            "line2": address.line2,
            "city": address.city,
            "region": address.region,
            "postal_code": address.postal_code,
            "country_code": address.country_code,
            "phone": address.phone,
        }
    if data.shipping_address is None:
        return None
    return data.shipping_address.model_dump(exclude={"label", "is_default"})


def get_order(
    db: Session,
    order_id: int,
    customer_id: int | None = None,
) -> Order:
    query = _order_query().where(Order.id == order_id)
    if customer_id is not None:
        query = query.where(Order.customer_id == customer_id)
    order = db.scalar(query)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found.")
    return order


def lock_order(db: Session, order_id: int) -> Order:
    order = db.scalar(
        select(Order).where(Order.id == order_id).with_for_update()
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found.")
    return order


def confirm_order(
    db: Session, order_id: int, actor_subject: str | None = None
) -> Order:
    try:
        order = lock_order(db, order_id)
        if order.status != "PENDING_PAYMENT":
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Only pending orders can be confirmed."
            )
        order.status = "CONFIRMED"
        db.add(
            OrderEvent(
                order_id=order.id,
                event_type="PAYMENT_CONFIRMED",
                actor_subject=actor_subject,
                data={},
            )
        )
        db.add(
            OutboxEvent(
                event_type="order.confirmed",
                aggregate_type="order",
                aggregate_id=str(order.id),
                payload={"order_id": order.id},
                attempts=0,
            )
        )
        db.commit()
        return get_order(db, order_id)
    except Exception:
        db.rollback()
        raise


def cancel_order(
    db: Session, order_id: int, actor_subject: str | None = None
) -> Order:
    try:
        order = lock_order(db, order_id)
        if order.status != "PENDING_PAYMENT":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Paid or fulfilled orders require the refund workflow.",
            )
        release_reserved_allocations(db, order_id)
        order.status = "CANCELLED"
        db.add(
            OrderEvent(
                order_id=order.id,
                event_type="ORDER_CANCELLED",
                actor_subject=actor_subject,
                data={},
            )
        )
        db.commit()
        return get_order(db, order_id)
    except Exception:
        db.rollback()
        raise


def release_reserved_allocations(db: Session, order_id: int) -> None:
    allocations = db.scalars(
        select(InventoryAllocation)
        .join(OrderItem, OrderItem.id == InventoryAllocation.order_item_id)
        .where(
            OrderItem.order_id == order_id,
            InventoryAllocation.status == "RESERVED",
        )
        .order_by(InventoryAllocation.inventory_id, InventoryAllocation.id)
        .with_for_update()
    ).all()
    inventory_ids = sorted({allocation.inventory_id for allocation in allocations})
    inventories = {
        inventory.id: inventory
        for inventory in db.scalars(
            select(Inventory)
            .where(Inventory.id.in_(inventory_ids))
            .order_by(Inventory.id)
            .with_for_update()
        ).all()
    }
    if len(inventories) != len(inventory_ids):
        raise HTTPException(status.HTTP_409_CONFLICT, "Allocation inventory is missing")
    for allocation in allocations:
        inventory = inventories[allocation.inventory_id]
        if inventory.quantity_reserved < allocation.quantity:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Inventory reservation is inconsistent.",
            )
    for allocation in allocations:
        inventories[allocation.inventory_id].quantity_reserved -= allocation.quantity
        allocation.status = "RELEASED"


def list_orders(
    db: Session,
    limit: int = 20,
    offset: int = 0,
    customer_id: int | None = None,
    order_status: str | None = None,
) -> dict:
    filters = []
    if customer_id is not None:
        filters.append(Order.customer_id == customer_id)
    if order_status is not None:
        filters.append(Order.status == order_status)
    total = db.scalar(select(func.count()).select_from(Order).where(*filters))
    orders = db.scalars(
        _order_query()
        .where(*filters)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {"items": orders, "total": total or 0, "limit": limit, "offset": offset}
