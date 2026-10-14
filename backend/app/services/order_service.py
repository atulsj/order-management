from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.inventory import Inventory
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.schemas.order import OrderCreate


def create_order(db: Session, data: OrderCreate) -> Order:
    # Combine repeated product IDs into one requested quantity.
    requested: dict[int, int] = {}

    for item in data.items:
        requested[item.product_id] = (
            requested.get(item.product_id, 0) + item.quantity
        )

    product_ids = sorted(requested)

    try:
        # Lock products in a consistent order to reduce deadlock risk.
        products = db.scalars(
            select(Product)
            .where(Product.id.in_(product_ids))
            .order_by(Product.id)
            .with_for_update()
        ).all()

        product_by_id = {product.id: product for product in products}

        if len(product_by_id) != len(product_ids):
            raise HTTPException(
                status_code=404,
                detail="One or more products were not found.",
            )

        for product in products:
            if not product.is_active:
                raise HTTPException(
                    status_code=409,
                    detail=f"Product {product.id} is inactive.",
                )

        # Lock inventory rows in the same product-ID order.
        inventories = db.scalars(
            select(Inventory)
            .where(Inventory.product_id.in_(product_ids))
            .order_by(Inventory.product_id)
            .with_for_update()
        ).all()

        inventory_by_product = {
            inventory.product_id: inventory for inventory in inventories
        }

        if len(inventory_by_product) != len(product_ids):
            raise HTTPException(
                status_code=409,
                detail="Inventory is not configured for one or more products.",
            )

        # Validate every requested quantity before modifying stock.
        for product_id, quantity in requested.items():
            inventory = inventory_by_product[product_id]
            available = (
                inventory.quantity_on_hand - inventory.quantity_reserved
            )

            if available < quantity:
                raise HTTPException(
                    status_code=409,
                    detail=f"Insufficient stock for product {product_id}.",
                )

        order_items: list[OrderItem] = []
        total = Decimal("0.00")

        for product_id in product_ids:
            product = product_by_id[product_id]
            quantity = requested[product_id]

            inventory = inventory_by_product[product_id]
            inventory.quantity_reserved += quantity

            unit_price = product.price
            total += unit_price * quantity

            order_items.append(
                OrderItem(
                    product_id=product_id,
                    quantity=quantity,
                    unit_price=unit_price,
                )
            )

        order = Order(
            status="PENDING_PAYMENT",
            total_amount=total,
            items=order_items,
        )

        db.add(order)
        db.commit()

        # Reload relationships so the response contains all order items.
        saved_order = db.scalar(
            select(Order)
            .where(Order.id == order.id)
            .options(selectinload(Order.items))
        )

        if saved_order is None:
            raise RuntimeError("Created order could not be reloaded.")

        return saved_order

    except Exception:
        db.rollback()
        raise


def get_order(db: Session, order_id: int) -> Order:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
    )

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found.",
        )

    return order


def _get_order_for_update(db: Session, order_id: int) -> Order:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
    )

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found.",
        )

    # Load order items within the current transaction.
    _ = order.items
    return order


def confirm_order(db: Session, order_id: int) -> Order:
    try:
        order = _get_order_for_update(db, order_id)

        if order.status != "PENDING_PAYMENT":
            raise HTTPException(
                status_code=409,
                detail="Only pending orders can be confirmed.",
            )

        product_ids = sorted(
            item.product_id for item in order.items
        )

        inventories = db.scalars(
            select(Inventory)
            .where(Inventory.product_id.in_(product_ids))
            .order_by(Inventory.product_id)
            .with_for_update()
        ).all()

        inventory_by_product = {
            inventory.product_id: inventory
            for inventory in inventories
        }

        if len(inventory_by_product) != len(set(product_ids)):
            raise HTTPException(
                status_code=409,
                detail="Inventory is missing for an order item.",
            )

        for item in order.items:
            inventory = inventory_by_product[item.product_id]

            if (
                inventory.quantity_reserved < item.quantity
                or inventory.quantity_on_hand < item.quantity
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Inventory reservation is inconsistent.",
                )

        for item in order.items:
            inventory = inventory_by_product[item.product_id]
            inventory.quantity_reserved -= item.quantity
            inventory.quantity_on_hand -= item.quantity

        order.status = "CONFIRMED"
        db.commit()

        return get_order(db, order_id)

    except Exception:
        db.rollback()
        raise


def cancel_order(db: Session, order_id: int) -> Order:
    try:
        order = _get_order_for_update(db, order_id)

        if order.status != "PENDING_PAYMENT":
            raise HTTPException(
                status_code=409,
                detail="Only pending orders can be cancelled.",
            )

        product_ids = sorted(
            item.product_id for item in order.items
        )

        inventories = db.scalars(
            select(Inventory)
            .where(Inventory.product_id.in_(product_ids))
            .order_by(Inventory.product_id)
            .with_for_update()
        ).all()

        inventory_by_product = {
            inventory.product_id: inventory
            for inventory in inventories
        }

        if len(inventory_by_product) != len(set(product_ids)):
            raise HTTPException(
                status_code=409,
                detail="Inventory is missing for an order item.",
            )

        for item in order.items:
            inventory = inventory_by_product[item.product_id]

            if inventory.quantity_reserved < item.quantity:
                raise HTTPException(
                    status_code=409,
                    detail="Inventory reservation is inconsistent.",
                )

        for item in order.items:
            inventory = inventory_by_product[item.product_id]
            inventory.quantity_reserved -= item.quantity

        order.status = "CANCELLED"
        db.commit()

        return get_order(db, order_id)

    except Exception:
        db.rollback()
        raise