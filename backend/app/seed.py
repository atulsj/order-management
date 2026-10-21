from decimal import Decimal

from sqlalchemy import select

from app.database.connection import SessionLocal
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.stock_movement import StockMovement
from app.models.warehouse import Warehouse


def seed() -> None:
    with SessionLocal() as db:
        warehouses = [
            ("EAST", "East Distribution Center", 10),
            ("WEST", "West Distribution Center", 20),
        ]
        for code, name, priority in warehouses:
            if db.scalar(select(Warehouse).where(Warehouse.code == code)) is None:
                db.add(Warehouse(code=code, name=name, priority=priority))
        db.flush()
        products = [
            ("OMS-LAMP-01", "Route Desk Lamp", "89.00"),
            ("OMS-BAG-01", "Transit Weekender", "149.00"),
            ("OMS-MUG-01", "Dispatch Travel Mug", "32.00"),
        ]
        for sku, name, price in products:
            product = db.scalar(select(Product).where(Product.sku == sku))
            if product is None:
                product = Product(
                    sku=sku,
                    name=name,
                    description="Seeded product for the OMS learning environment.",
                    price=Decimal(price),
                )
                db.add(product)
                db.flush()
            for warehouse in db.scalars(
                select(Warehouse).where(Warehouse.code.in_(["EAST", "WEST"]))
            ).all():
                existing = db.scalar(
                    select(Inventory).where(
                        Inventory.product_id == product.id,
                        Inventory.warehouse_id == warehouse.id,
                    )
                )
                if existing is None:
                    inventory = Inventory(
                        product_id=product.id,
                        warehouse_id=warehouse.id,
                        quantity_on_hand=25,
                        quantity_reserved=0,
                    )
                    db.add(inventory)
                    db.flush()
                    db.add(
                        StockMovement(
                            inventory_id=inventory.id,
                            movement_type="RECEIPT",
                            quantity_delta=25,
                            reason="Learning environment seed",
                            actor_subject="system:seed",
                            details={},
                        )
                    )
        db.commit()


if __name__ == "__main__":
    seed()
