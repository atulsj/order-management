from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory import Inventory
from app.models.product import Product
from app.models.stock_movement import StockMovement
from app.models.warehouse import Warehouse
from app.schemas.inventory import InventoryAdjust, InventoryCreate


def create_inventory(db: Session, data: InventoryCreate) -> Inventory:
    product = db.get(Product, data.product_id)
    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found.",
        )

    warehouse = db.get(Warehouse, data.warehouse_id)
    if warehouse is None:
        raise HTTPException(status_code=404, detail="Warehouse not found.")

    existing = db.scalar(
        select(Inventory).where(
            Inventory.product_id == data.product_id,
            Inventory.warehouse_id == data.warehouse_id,
        )
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Inventory already exists for this product.",
        )

    inventory = Inventory(
        product_id=data.product_id,
        warehouse_id=data.warehouse_id,
        quantity_on_hand=data.quantity_on_hand,
        quantity_reserved=0,
    )

    db.add(inventory)
    db.flush()
    if data.quantity_on_hand:
        db.add(
            StockMovement(
                inventory_id=inventory.id,
                movement_type="RECEIPT",
                quantity_delta=data.quantity_on_hand,
                reason="Initial inventory",
                details={},
            )
        )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Inventory could not be created; check for a concurrent request.",
        ) from exc

    db.refresh(inventory)
    return inventory


def get_inventory(
    db: Session, product_id: int, warehouse_id: int = 1
) -> Inventory:
    inventory = db.scalar(
        select(Inventory).where(
            Inventory.product_id == product_id,
            Inventory.warehouse_id == warehouse_id,
        )
    )

    if inventory is None:
        raise HTTPException(
            status_code=404,
            detail="Inventory not found for this product.",
        )

    return inventory


def receive_stock(
    db: Session,
    product_id: int,
    quantity: int,
    warehouse_id: int = 1,
    actor_subject: str | None = None,
) -> Inventory:
    inventory = db.scalar(
        select(Inventory)
        .where(
            Inventory.product_id == product_id,
            Inventory.warehouse_id == warehouse_id,
        )
        .with_for_update()
    )

    if inventory is None:
        raise HTTPException(
            status_code=404,
            detail="Inventory not found for this product.",
        )

    inventory.quantity_on_hand += quantity
    db.add(
        StockMovement(
            inventory_id=inventory.id,
            movement_type="RECEIPT",
            quantity_delta=quantity,
            reason="Stock received",
            actor_subject=actor_subject,
            details={},
        )
    )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Stock update violated an inventory constraint.",
        ) from exc

    db.refresh(inventory)
    return inventory


def adjust_stock(
    db: Session,
    inventory_id: int,
    data: InventoryAdjust,
    actor_subject: str,
) -> Inventory:
    inventory = db.scalar(
        select(Inventory).where(Inventory.id == inventory_id).with_for_update()
    )
    if inventory is None:
        raise HTTPException(status_code=404, detail="Inventory not found.")
    new_on_hand = inventory.quantity_on_hand + data.quantity_delta
    if new_on_hand < inventory.quantity_reserved:
        raise HTTPException(
            status_code=409,
            detail="Adjustment would reduce stock below the reserved quantity.",
        )
    inventory.quantity_on_hand = new_on_hand
    db.add(
        StockMovement(
            inventory_id=inventory.id,
            movement_type="ADJUSTMENT",
            quantity_delta=data.quantity_delta,
            reason=data.reason,
            actor_subject=actor_subject,
            details={},
        )
    )
    db.commit()
    db.refresh(inventory)
    return inventory


def list_inventory(
    db: Session,
    warehouse_id: int | None = None,
    product_id: int | None = None,
) -> list[Inventory]:
    query = select(Inventory).order_by(Inventory.warehouse_id, Inventory.product_id)
    if warehouse_id is not None:
        query = query.where(Inventory.warehouse_id == warehouse_id)
    if product_id is not None:
        query = query.where(Inventory.product_id == product_id)
    return list(db.scalars(query).all())


def list_movements(
    db: Session, inventory_id: int, limit: int = 100
) -> list[StockMovement]:
    return list(
        db.scalars(
            select(StockMovement)
            .where(StockMovement.inventory_id == inventory_id)
            .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
            .limit(limit)
        ).all()
    )


def list_low_stock(
    db: Session, threshold: int = 5
) -> list[Inventory]:
    return list(
        db.scalars(
            select(Inventory)
            .where(
                Inventory.quantity_on_hand - Inventory.quantity_reserved
                <= threshold
            )
            .order_by(
                Inventory.quantity_on_hand - Inventory.quantity_reserved,
                Inventory.warehouse_id,
                Inventory.product_id,
            )
        ).all()
    )