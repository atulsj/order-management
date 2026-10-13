from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory import Inventory
from app.models.product import Product
from app.schemas.inventory import InventoryCreate


def create_inventory(db: Session, data: InventoryCreate) -> Inventory:
    product = db.get(Product, data.product_id)

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found.",
        )

    existing = db.scalar(
        select(Inventory).where(
            Inventory.product_id == data.product_id
        )
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Inventory already exists for this product.",
        )

    inventory = Inventory(
        product_id=data.product_id,
        quantity_on_hand=data.quantity_on_hand,
        quantity_reserved=0,
    )

    db.add(inventory)

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


def get_inventory(db: Session, product_id: int) -> Inventory:
    inventory = db.scalar(
        select(Inventory).where(
            Inventory.product_id == product_id
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
) -> Inventory:
    inventory = db.scalar(
        select(Inventory)
        .where(Inventory.product_id == product_id)
        .with_for_update()
    )

    if inventory is None:
        raise HTTPException(
            status_code=404,
            detail="Inventory not found for this product.",
        )

    inventory.quantity_on_hand += quantity

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