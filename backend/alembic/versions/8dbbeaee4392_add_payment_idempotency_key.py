"""add payment idempotency key

Revision ID: 8dbbeaee4392
Revises: bc765b59a54d
Create Date: 2026-10-17 15:22:32.891769

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8dbbeaee4392"
down_revision: Union[str, Sequence[str], None] = "bc765b59a54d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add the column as nullable so existing rows remain valid.
    op.add_column(
        "payments",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )

    # 2. Give existing payment records unique legacy keys.
    op.execute(
        """
        UPDATE payments
        SET idempotency_key = 'legacy-' || id::text
        WHERE idempotency_key IS NULL
        """
    )

    # 3. Enforce uniqueness in PostgreSQL.
    op.create_unique_constraint(
        "uq_payments_idempotency_key",
        "payments",
        ["idempotency_key"],
    )

    # 4. Require a key for every new payment record.
    op.alter_column(
        "payments",
        "idempotency_key",
        existing_type=sa.String(length=255),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_payments_idempotency_key",
        "payments",
        type_="unique",
    )
    op.drop_column("payments", "idempotency_key")
