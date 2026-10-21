from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.orm import Session

from app.core.auth import Principal, get_principal
from app.database.connection import get_db
from app.schemas.order import OrderCreate, OrderListResponse, OrderResponse
from app.services import customer_service, order_service, refund_service

router = APIRouter(prefix="/orders", tags=["Orders"])


def _customer_scope(db: Session, principal: Principal) -> int | None:
    if principal.has_any_role({"operator", "admin"}):
        return None
    return customer_service.get_or_create_customer(db, principal).id


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    data: OrderCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    db: Session = Depends(get_db),
) -> OrderResponse:
    customer = customer_service.get_or_create_customer(db, principal)
    return order_service.create_order(db, data, customer, principal.subject)


@router.get("", response_model=OrderListResponse)
def list_orders(
    principal: Annotated[Principal, Depends(get_principal)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    order_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> OrderListResponse:
    return order_service.list_orders(
        db,
        limit=limit,
        offset=offset,
        customer_id=_customer_scope(db, principal),
        order_status=order_status,
    )


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: int,
    principal: Annotated[Principal, Depends(get_principal)],
    db: Session = Depends(get_db),
) -> OrderResponse:
    return order_service.get_order(db, order_id, _customer_scope(db, principal))


@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: int,
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=1, max_length=255
    ),
    db: Session = Depends(get_db),
) -> OrderResponse:
    scoped_order = order_service.get_order(db, order_id, _customer_scope(db, principal))
    if scoped_order.status == "PENDING_PAYMENT":
        return order_service.cancel_order(db, scoped_order.id, principal.subject)
    return refund_service.request_refund_cancellation(
        db, scoped_order.id, idempotency_key.strip(), principal.subject
    )
