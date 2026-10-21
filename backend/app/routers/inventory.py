from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_roles
from app.database.connection import get_db
from app.schemas.inventory import (
    InventoryAdjust,
    InventoryCreate,
    InventoryReceive,
    InventoryResponse,
    StockMovementResponse,
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
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    db: Session = Depends(get_db),
) -> InventoryResponse:
    return inventory_service.create_inventory(db, data)


@router.get(
    "/products/{product_id}",
    response_model=InventoryResponse,
)
def get_inventory(
    product_id: int,
    warehouse_id: int = Query(default=1, gt=0),
    db: Session = Depends(get_db),
) -> InventoryResponse:
    return inventory_service.get_inventory(db, product_id, warehouse_id)


@router.post(
    "/{product_id}/receive",
    response_model=InventoryResponse,
)
def receive_stock(
    product_id: int,
    data: InventoryReceive,
    principal: Annotated[Principal, Depends(require_roles("admin", "operator"))],
    warehouse_id: int = Query(default=1, gt=0),
    db: Session = Depends(get_db),
) -> InventoryResponse:
    return inventory_service.receive_stock(
        db,
        product_id,
        data.quantity,
        warehouse_id,
        principal.subject,
    )


@router.get("", response_model=list[InventoryResponse])
def list_inventory(
    principal: Annotated[
        Principal, Depends(require_roles("admin", "operator"))
    ],
    warehouse_id: int | None = Query(default=None, gt=0),
    product_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
) -> list[InventoryResponse]:
    return inventory_service.list_inventory(db, warehouse_id, product_id)


@router.post("/{inventory_id}/adjust", response_model=InventoryResponse)
def adjust_inventory(
    inventory_id: int,
    data: InventoryAdjust,
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    db: Session = Depends(get_db),
) -> InventoryResponse:
    return inventory_service.adjust_stock(db, inventory_id, data, principal.subject)


@router.get(
    "/{inventory_id}/movements",
    response_model=list[StockMovementResponse],
)
def list_movements(
    inventory_id: int,
    principal: Annotated[
        Principal, Depends(require_roles("admin", "operator"))
    ],
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[StockMovementResponse]:
    return inventory_service.list_movements(db, inventory_id, limit)


@router.get("/alerts/low-stock", response_model=list[InventoryResponse])
def low_stock(
    principal: Annotated[
        Principal, Depends(require_roles("admin", "operator"))
    ],
    threshold: int = Query(default=5, ge=0, le=100000),
    db: Session = Depends(get_db),
) -> list[InventoryResponse]:
    return inventory_service.list_low_stock(db, threshold)