
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.schemas.order import OrderCreate, OrderResponse
from app.services import order_service

from app.schemas.order import OrderListResponse

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    data: OrderCreate,
    db: Session = Depends(get_db),
) -> OrderResponse:
    return order_service.create_order(db, data)

@router.get(
    "",
    response_model=OrderListResponse,
)
def list_orders(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> OrderListResponse:
    return order_service.list_orders(
        db,
        limit=limit,
        offset=offset,
    )

@router.get(
    "/{order_id}",
    response_model=OrderResponse,
)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
) -> OrderResponse:
    return order_service.get_order(db, order_id)


@router.post(
    "/{order_id}/confirm",
    response_model=OrderResponse,
)
def confirm_order(
    order_id: int,
    db: Session = Depends(get_db),
) -> OrderResponse:
    return order_service.confirm_order(db, order_id)


@router.post(
    "/{order_id}/cancel",
    response_model=OrderResponse,
)
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
) -> OrderResponse:
    return order_service.cancel_order(db, order_id)
