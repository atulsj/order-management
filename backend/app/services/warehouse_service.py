from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.warehouse import Warehouse
from app.schemas.warehouse import WarehouseCreate, WarehouseUpdate


def create_warehouse(db: Session, data: WarehouseCreate) -> Warehouse:
    warehouse = Warehouse(**data.model_dump())
    db.add(warehouse)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Warehouse code already exists") from exc
    db.refresh(warehouse)
    return warehouse


def list_warehouses(db: Session, active_only: bool = False) -> list[Warehouse]:
    query = select(Warehouse).order_by(Warehouse.priority, Warehouse.id)
    if active_only:
        query = query.where(Warehouse.is_active.is_(True))
    return list(db.scalars(query).all())


def get_warehouse(db: Session, warehouse_id: int) -> Warehouse:
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Warehouse not found")
    return warehouse


def update_warehouse(
    db: Session, warehouse_id: int, data: WarehouseUpdate
) -> Warehouse:
    warehouse = get_warehouse(db, warehouse_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(warehouse, field, value)
    db.commit()
    db.refresh(warehouse)
    return warehouse
