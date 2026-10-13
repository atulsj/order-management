
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.connection import engine, get_db
from app.routers.product import router as product_router

from app.routers.inventory import router as inventory_router

app = FastAPI(
    title="Order Management System API",
    description="API for managing products, inventory, and customer orders.",
    version="0.1.0",
)

app.include_router(product_router)
app.include_router(inventory_router)

@app.get("/", tags=["General"])
def root() -> dict[str, str]:
    return {"message": "Order Management System API"}


@app.get("/health", tags=["General"])
def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/health/database", tags=["Health"])
def database_health_check(
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        return {"database": "connected"}
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Database connection failed",
        ) from exc

