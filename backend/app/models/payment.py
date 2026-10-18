
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from sqlalchemy import Boolean, Integer
from sqlalchemy import UniqueConstraint

class Payment(Base):
    __tablename__ = "payments"

    __table_args__ = (
        CheckConstraint(
            "amount > 0",
            name="ck_payments_amount_positive",
        ),
        UniqueConstraint(
            "order_id",  
            "attempt_number",
            name="uq_payments_order_attempt",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )
    
    provider_idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        Enum(
            "PENDING",
            "SUCCEEDED",
            "FAILED",
            "REFUNDED",
            name="payment_status",
        ),
        nullable=False,
        server_default=text("'PENDING'"),
    )

    provider_reference: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Attempt number within this order: 1, 2, or 3.
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )

    # True when the payment needs operational investigation.
    requires_review: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    review_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # Reconciliation scheduling and audit information.
    last_reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    next_reconciliation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Deadline for retrying after a definitive failure.
    retry_window_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    order: Mapped["Order"] = relationship()
