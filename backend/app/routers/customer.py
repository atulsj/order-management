from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.auth import Principal, get_principal
from app.database.connection import get_db
from app.schemas.customer import AddressCreate, AddressResponse, CustomerResponse
from app.services import customer_service

router = APIRouter(prefix="/me", tags=["Customer"])


@router.get("", response_model=CustomerResponse)
def get_profile(
    principal: Annotated[Principal, Depends(get_principal)],
    db: Session = Depends(get_db),
) -> CustomerResponse:
    return customer_service.get_profile(db, principal)


@router.post(
    "/addresses",
    response_model=AddressResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_address(
    data: AddressCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    db: Session = Depends(get_db),
) -> AddressResponse:
    return customer_service.add_address(db, principal, data)


@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(
    address_id: int,
    principal: Annotated[Principal, Depends(get_principal)],
    db: Session = Depends(get_db),
) -> Response:
    customer_service.delete_address(db, principal, address_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
