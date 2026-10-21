from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.allocation import InventoryAllocation
from app.models.integration_event import OutboxEvent
from app.models.inventory import Inventory
from app.models.order import Order
from app.models.order_event import OrderEvent
from app.models.order_item import OrderItem
from app.models.shipment import Shipment, ShipmentItem
from app.models.stock_movement import StockMovement
from app.schemas.shipment import ShipmentCreate, ShipmentUpdate


def _get_shipment(db: Session, shipment_id: int, for_update: bool = False) -> Shipment:
    query = (
        select(Shipment)
        .where(Shipment.id == shipment_id)
        .options(selectinload(Shipment.items))
    )
    if for_update:
        query = query.with_for_update()
    shipment = db.scalar(query)
    if shipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shipment not found")
    return shipment


def create_shipment(
    db: Session, data: ShipmentCreate, actor_subject: str
) -> Shipment:
    try:
        order = db.scalar(
            select(Order).where(Order.id == data.order_id).with_for_update()
        )
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        if order.status not in {"CONFIRMED", "PARTIALLY_FULFILLED"}:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Order is not ready for fulfillment"
            )
        allocation_ids = sorted(set(data.allocation_ids))
        allocations = db.scalars(
            select(InventoryAllocation)
            .join(OrderItem, OrderItem.id == InventoryAllocation.order_item_id)
            .where(
                InventoryAllocation.id.in_(allocation_ids),
                OrderItem.order_id == order.id,
            )
            .order_by(InventoryAllocation.inventory_id, InventoryAllocation.id)
            .with_for_update()
        ).all()
        if len(allocations) != len(allocation_ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Allocation not found")
        if any(allocation.status != "RESERVED" for allocation in allocations):
            raise HTTPException(status.HTTP_409_CONFLICT, "Allocation is not available")
        allocation_inventories = [
            db.get(Inventory, allocation.inventory_id) for allocation in allocations
        ]
        if any(inventory is None for inventory in allocation_inventories):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Allocation inventory is missing"
            )
        warehouse_ids = {
            inventory.warehouse_id
            for inventory in allocation_inventories
            if inventory is not None
        }
        if len(warehouse_ids) != 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A shipment must contain allocations from one warehouse",
            )
        shipment = Shipment(
            order_id=order.id,
            warehouse_id=warehouse_ids.pop(),
            carrier=data.carrier,
            tracking_number=data.tracking_number,
            items=[
                ShipmentItem(allocation_id=allocation.id, quantity=allocation.quantity)
                for allocation in allocations
            ],
        )
        db.add(shipment)
        db.flush()
        db.add(
            OrderEvent(
                order_id=order.id,
                event_type="SHIPMENT_CREATED",
                actor_subject=actor_subject,
                data={"shipment_id": shipment.id},
            )
        )
        db.commit()
        return _get_shipment(db, shipment.id)
    except Exception:
        db.rollback()
        raise


def update_shipment(
    db: Session, shipment_id: int, data: ShipmentUpdate
) -> Shipment:
    shipment = _get_shipment(db, shipment_id, for_update=True)
    if shipment.status != "PENDING":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only pending shipments can be edited")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(shipment, field, value)
    db.commit()
    return _get_shipment(db, shipment_id)


def mark_shipped(db: Session, shipment_id: int, actor_subject: str) -> Shipment:
    try:
        preview = db.get(Shipment, shipment_id)
        if preview is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Shipment not found")
        order = db.scalar(
            select(Order).where(Order.id == preview.order_id).with_for_update()
        )
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        shipment = _get_shipment(db, shipment_id, for_update=True)
        if shipment.status != "PENDING":
            raise HTTPException(status.HTTP_409_CONFLICT, "Shipment is not pending")
        allocations = db.scalars(
            select(InventoryAllocation)
            .where(
                InventoryAllocation.id.in_(
                    sorted(item.allocation_id for item in shipment.items)
                )
            )
            .order_by(InventoryAllocation.inventory_id, InventoryAllocation.id)
            .with_for_update()
        ).all()
        inventories = {
            inventory.id: inventory
            for inventory in db.scalars(
                select(Inventory)
                .where(
                    Inventory.id.in_(
                        sorted({allocation.inventory_id for allocation in allocations})
                    )
                )
                .order_by(Inventory.id)
                .with_for_update()
            ).all()
        }
        for allocation in allocations:
            inventory = inventories[allocation.inventory_id]
            if (
                allocation.status != "RESERVED"
                or inventory.quantity_reserved < allocation.quantity
                or inventory.quantity_on_hand < allocation.quantity
            ):
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "Shipment inventory is inconsistent"
                )
        for allocation in allocations:
            inventory = inventories[allocation.inventory_id]
            inventory.quantity_reserved -= allocation.quantity
            inventory.quantity_on_hand -= allocation.quantity
            allocation.status = "CONSUMED"
            db.add(
                StockMovement(
                    inventory_id=inventory.id,
                    movement_type="SHIPMENT",
                    quantity_delta=-allocation.quantity,
                    reason=f"Shipment {shipment.id}",
                    actor_subject=actor_subject,
                    reference_type="shipment",
                    reference_id=str(shipment.id),
                    details={},
                )
            )
        shipment.status = "SHIPPED"
        shipment.shipped_at = datetime.now(UTC)
        remaining = db.scalar(
            select(InventoryAllocation.id)
            .join(OrderItem, OrderItem.id == InventoryAllocation.order_item_id)
            .where(
                OrderItem.order_id == shipment.order_id,
                InventoryAllocation.status == "RESERVED",
            )
            .limit(1)
        )
        order.status = "PARTIALLY_FULFILLED" if remaining else "FULFILLED"
        db.add(
            OrderEvent(
                order_id=order.id,
                event_type="SHIPMENT_SHIPPED",
                actor_subject=actor_subject,
                data={"shipment_id": shipment.id},
            )
        )
        db.add(
            OutboxEvent(
                event_type="shipment.shipped",
                aggregate_type="shipment",
                aggregate_id=str(shipment.id),
                payload={"shipment_id": shipment.id, "order_id": order.id},
                attempts=0,
            )
        )
        db.commit()
        return _get_shipment(db, shipment_id)
    except Exception:
        db.rollback()
        raise


def mark_delivered(db: Session, shipment_id: int, actor_subject: str) -> Shipment:
    preview = db.get(Shipment, shipment_id)
    if preview is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shipment not found")
    order = db.scalar(
        select(Order).where(Order.id == preview.order_id).with_for_update()
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    shipment = _get_shipment(db, shipment_id, for_update=True)
    if shipment.status != "SHIPPED":
        raise HTTPException(status.HTTP_409_CONFLICT, "Shipment has not been shipped")
    shipment.status = "DELIVERED"
    shipment.delivered_at = datetime.now(UTC)
    db.add(
        OrderEvent(
            order_id=shipment.order_id,
            event_type="SHIPMENT_DELIVERED",
            actor_subject=actor_subject,
            data={"shipment_id": shipment.id},
        )
    )
    db.commit()
    return _get_shipment(db, shipment_id)


def list_shipments(db: Session, order_id: int | None = None) -> list[Shipment]:
    query = select(Shipment).options(selectinload(Shipment.items)).order_by(Shipment.id.desc())
    if order_id is not None:
        query = query.where(Shipment.order_id == order_id)
    return list(db.scalars(query).all())
