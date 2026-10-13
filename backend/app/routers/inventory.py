from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.schemas.inventory import (
    InventoryCreate,
    InventoryReceive,
    InventoryResponse,
)
from app.services import inventory_service

router = APIRouter(
    prefix="/inventory",
    tags=["Inventory"],
)


@router.post(
    "",
    response_model=InventoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_inventory(
    data: InventoryCreate,
    db: Session = Depends(get_db),
) -> InventoryResponse:
    return inventory_service.create_inventory(db, data)


@router.get(
    "/{product_id}",
    response_model=InventoryResponse,
)
def get_inventory(
    product_id: int,
    db: Session = Depends(get_db),
) -> InventoryResponse:
    return inventory_service.get_inventory(db, product_id)


@router.post(
    "/{product_id}/receive",
    response_model=InventoryResponse,
)
def receive_stock(
    product_id: int,
    data: InventoryReceive,
    db: Session = Depends(get_db),
) -> InventoryResponse:
    return inventory_service.receive_stock(
        db,
        product_id,
        data.quantity,
    )