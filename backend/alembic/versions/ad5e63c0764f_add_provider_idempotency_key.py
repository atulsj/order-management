
"""add provider idempotency key

Revision ID: ad5e63c0764f
Revises: 7dacd345011e
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ad5e63c0764f"
down_revision: Union[str, Sequence[str], None] = "7dacd345011e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add nullable first so existing payment rows remain valid.
    op.add_column(
        "payments",
        sa.Column(
            "provider_idempotency_key",
            sa.String(length=255),
            nullable=True,
        ),
    )

    # 2. Backfill a unique value for every historical payment.
    op.execute(
        """
        UPDATE payments
        SET provider_idempotency_key = 'legacy-provider-' || id::text
        WHERE provider_idempotency_key IS NULL
        """
    )

    # 3. Enforce uniqueness and require a value for future records.
    op.create_unique_constraint(
        "uq_payments_provider_idempotency_key",
        "payments",
        ["provider_idempotency_key"],
    )

    op.alter_column(
        "payments",
        "provider_idempotency_key",
        existing_type=sa.String(length=255),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_payments_provider_idempotency_key",
        "payments",
        type_="unique",
    )
    op.drop_column("payments", "provider_idempotency_key")
