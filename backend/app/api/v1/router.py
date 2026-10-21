from fastapi import APIRouter

from app.routers.customer import router as customer_router
from app.routers.inventory import router as inventory_router
from app.routers.order import router as order_router
from app.routers.payment import router as payment_router
from app.routers.product import router as product_router
from app.routers.shipment import router as shipment_router
from app.routers.warehouse import router as warehouse_router

api_router = APIRouter()
api_router.include_router(product_router)
api_router.include_router(inventory_router)
api_router.include_router(order_router)
api_router.include_router(payment_router)
api_router.include_router(customer_router)
api_router.include_router(warehouse_router)
api_router.include_router(shipment_router)
