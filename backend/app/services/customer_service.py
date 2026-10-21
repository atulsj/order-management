from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.auth import Principal
from app.models.customer import Customer, CustomerAddress
from app.schemas.customer import AddressCreate


def get_or_create_customer(db: Session, principal: Principal) -> Customer:
    customer = db.scalar(
        select(Customer)
        .where(Customer.keycloak_subject == principal.subject)
        .options(selectinload(Customer.addresses))
    )
    if customer is None:
        customer = Customer(
            keycloak_subject=principal.subject,
            email=principal.email,
            display_name=principal.name,
        )
        db.add(customer)
        db.flush()
    else:
        customer.email = principal.email
        customer.display_name = principal.name
    return customer


def get_profile(db: Session, principal: Principal) -> Customer:
    customer = get_or_create_customer(db, principal)
    db.commit()
    return reload_customer(db, customer.id)


def add_address(db: Session, principal: Principal, data: AddressCreate) -> CustomerAddress:
    customer = get_or_create_customer(db, principal)
    if data.is_default:
        for address in customer.addresses:
            address.is_default = False
    address = CustomerAddress(customer=customer, **data.model_dump())
    db.add(address)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Address label already exists") from exc
    db.refresh(address)
    return address


def delete_address(db: Session, principal: Principal, address_id: int) -> None:
    customer = get_or_create_customer(db, principal)
    address = db.scalar(
        select(CustomerAddress).where(
            CustomerAddress.id == address_id,
            CustomerAddress.customer_id == customer.id,
        )
    )
    if address is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Address not found")
    db.delete(address)
    db.commit()


def reload_customer(db: Session, customer_id: int) -> Customer:
    customer = db.scalar(
        select(Customer)
        .where(Customer.id == customer_id)
        .options(selectinload(Customer.addresses))
    )
    if customer is None:
        raise RuntimeError("Customer could not be reloaded")
    return customer
