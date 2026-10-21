
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_roles
from app.database.connection import get_db
from app.schemas.product import (
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)
from app.services import product_service

router = APIRouter(prefix="/products", tags=["Products"])


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    data: ProductCreate,
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    db: Session = Depends(get_db),
) -> ProductResponse:
    return product_service.create_product(db, data)


@router.get("", response_model=ProductListResponse)
def list_products(
    search: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ProductListResponse:
    return product_service.list_products(db, search, limit, offset)


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
) -> ProductResponse:
    return product_service.get_product(db, product_id)


@router.patch("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int,
    data: ProductUpdate,
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    db: Session = Depends(get_db),
) -> ProductResponse:
    return product_service.update_product(db, product_id, data)


@router.delete("/{product_id}", response_model=ProductResponse)
def delete_product(
    product_id: int,
    principal: Annotated[Principal, Depends(require_roles("admin"))],
    db: Session = Depends(get_db),
) -> ProductResponse:
    return product_service.deactivate_product(db, product_id)
