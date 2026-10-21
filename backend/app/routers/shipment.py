from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_roles
from app.database.connection import get_db
from app.schemas.shipment import ShipmentCreate, ShipmentResponse, ShipmentUpdate
from app.services import shipment_service

router = APIRouter(prefix="/shipments", tags=["Shipments"])
operator = require_roles("operator", "admin")


@router.post("", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
def create_shipment(
    data: ShipmentCreate,
    principal: Annotated[Principal, Depends(operator)],
    db: Session = Depends(get_db),
) -> ShipmentResponse:
    return shipment_service.create_shipment(db, data, principal.subject)


@router.get("", response_model=list[ShipmentResponse])
def list_shipments(
    principal: Annotated[Principal, Depends(operator)],
    order_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
) -> list[ShipmentResponse]:
    return shipment_service.list_shipments(db, order_id)


@router.patch("/{shipment_id}", response_model=ShipmentResponse)
def update_shipment(
    shipment_id: int,
    data: ShipmentUpdate,
    principal: Annotated[Principal, Depends(operator)],
    db: Session = Depends(get_db),
) -> ShipmentResponse:
    return shipment_service.update_shipment(db, shipment_id, data)


@router.post("/{shipment_id}/ship", response_model=ShipmentResponse)
def mark_shipped(
    shipment_id: int,
    principal: Annotated[Principal, Depends(operator)],
    db: Session = Depends(get_db),
) -> ShipmentResponse:
    return shipment_service.mark_shipped(db, shipment_id, principal.subject)


@router.post("/{shipment_id}/deliver", response_model=ShipmentResponse)
def mark_delivered(
    shipment_id: int,
    principal: Annotated[Principal, Depends(operator)],
    db: Session = Depends(get_db),
) -> ShipmentResponse:
    return shipment_service.mark_delivered(db, shipment_id, principal.subject)
