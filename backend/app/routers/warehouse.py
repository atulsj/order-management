from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_roles
from app.database.connection import get_db
from app.schemas.warehouse import WarehouseCreate, WarehouseResponse, WarehouseUpdate
from app.services import warehouse_service

router = APIRouter(prefix="/warehouses", tags=["Warehouses"])


@router.post("", response_model=WarehouseResponse, status_code=status.HTTP_201_CREATED)
def create_warehouse(
    data: WarehouseCreate,
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    db: Session = Depends(get_db),
) -> WarehouseResponse:
    return warehouse_service.create_warehouse(db, data)


@router.get("", response_model=list[WarehouseResponse])
def list_warehouses(
    principal: Annotated[
        Principal, Depends(require_roles("admin", "operator"))
    ],
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[WarehouseResponse]:
    return warehouse_service.list_warehouses(db, active_only)


@router.patch("/{warehouse_id}", response_model=WarehouseResponse)
def update_warehouse(
    warehouse_id: int,
    data: WarehouseUpdate,
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    db: Session = Depends(get_db),
) -> WarehouseResponse:
    return warehouse_service.update_warehouse(db, warehouse_id, data)
