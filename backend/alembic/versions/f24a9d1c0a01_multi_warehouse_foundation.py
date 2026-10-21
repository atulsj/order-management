"""multi warehouse foundation

Revision ID: f24a9d1c0a01
Revises: ad5e63c0764f
Create Date: 2026-10-21 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f24a9d1c0a01"
down_revision: str | Sequence[str] | None = "ad5e63c0764f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_warehouses_code", "warehouses", ["code"])
    op.execute(
        "INSERT INTO warehouses (id, code, name, priority) "
        "VALUES (1, 'DEFAULT', 'Default Warehouse', 100)"
    )
    op.execute(
        "SELECT setval(pg_get_serial_sequence('warehouses', 'id'), "
        "GREATEST((SELECT MAX(id) FROM warehouses), 1))"
    )

    op.add_column(
        "inventory",
        sa.Column(
            "warehouse_id",
            sa.Integer(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT"),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.drop_constraint("inventory_product_id_key", "inventory", type_="unique")
    op.create_unique_constraint(
        "uq_inventory_warehouse_product", "inventory", ["warehouse_id", "product_id"]
    )
    op.create_index("ix_inventory_warehouse_id", "inventory", ["warehouse_id"])
    op.create_index("ix_inventory_product_id", "inventory", ["product_id"])

    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keycloak_subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320)),
        sa.Column("display_name", sa.String(200)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("keycloak_subject"),
    )
    op.create_index("ix_customers_keycloak_subject", "customers", ["keycloak_subject"])
    op.create_table(
        "customer_addresses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("recipient_name", sa.String(200), nullable=False),
        sa.Column("line1", sa.String(200), nullable=False),
        sa.Column("line2", sa.String(200)),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("region", sa.String(120), nullable=False),
        sa.Column("postal_code", sa.String(32), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("phone", sa.String(32)),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "label", name="uq_customer_address_label"),
    )
    op.create_index("ix_customer_addresses_customer_id", "customer_addresses", ["customer_id"])

    op.execute("ALTER TABLE orders ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE orders ALTER COLUMN status TYPE VARCHAR(32) USING status::text"
    )
    op.execute("DROP TYPE IF EXISTS order_status")
    op.alter_column("orders", "status", server_default=sa.text("'PENDING_PAYMENT'"))
    op.add_column(
        "orders",
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("currency", sa.String(3), server_default=sa.text("'USD'"), nullable=False),
    )
    op.add_column(
        "orders",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_status", "orders", ["status"])

    op.create_table(
        "order_addresses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient_name", sa.String(200), nullable=False),
        sa.Column("line1", sa.String(200), nullable=False),
        sa.Column("line2", sa.String(200)),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("region", sa.String(120), nullable=False),
        sa.Column("postal_code", sa.String(32), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("phone", sa.String(32)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
    )
    op.create_index("ix_order_addresses_order_id", "order_addresses", ["order_id"])
    op.create_table(
        "order_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_subject", sa.String(255)),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_events_order_id", "order_events", ["order_id"])
    op.create_index("ix_order_events_event_type", "order_events", ["event_type"])
    op.create_index("ix_order_events_created_at", "order_events", ["created_at"])

    op.create_table(
        "inventory_allocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "order_item_id",
            sa.Integer(),
            sa.ForeignKey("order_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "inventory_id",
            sa.Integer(),
            sa.ForeignKey("inventory.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(24), server_default=sa.text("'RESERVED'"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity > 0", name="ck_allocations_quantity_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_allocations_order_item_id", "inventory_allocations", ["order_item_id"])
    op.create_index("ix_inventory_allocations_inventory_id", "inventory_allocations", ["inventory_id"])
    op.create_index("ix_inventory_allocations_status", "inventory_allocations", ["status"])
    op.execute(
        """
        INSERT INTO inventory_allocations (order_item_id, inventory_id, quantity, status)
        SELECT oi.id, i.id, oi.quantity, 'RESERVED'
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN inventory i ON i.product_id = oi.product_id AND i.warehouse_id = 1
        WHERE o.status = 'PENDING_PAYMENT'
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM inventory i
                LEFT JOIN inventory_allocations a
                    ON a.inventory_id = i.id
                    AND a.status = 'RESERVED'
                GROUP BY i.id, i.quantity_reserved
                HAVING i.quantity_reserved <> COALESCE(SUM(a.quantity), 0)
            ) THEN
                RAISE EXCEPTION
                    'Legacy reserved inventory does not match pending order allocations';
            END IF;
        END
        $$;
        """
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "inventory_id",
            sa.Integer(),
            sa.ForeignKey("inventory.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("movement_type", sa.String(32), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("actor_subject", sa.String(255)),
        sa.Column("reference_type", sa.String(64)),
        sa.Column("reference_id", sa.String(64)),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_movements_inventory_id", "stock_movements", ["inventory_id"])
    op.create_index("ix_stock_movements_movement_type", "stock_movements", ["movement_type"])
    op.create_index("ix_stock_movements_created_at", "stock_movements", ["created_at"])

    op.create_table(
        "shipments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.Integer(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("carrier", sa.String(100)),
        sa.Column("tracking_number", sa.String(200), unique=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shipments_order_id", "shipments", ["order_id"])
    op.create_index("ix_shipments_warehouse_id", "shipments", ["warehouse_id"])
    op.create_index("ix_shipments_status", "shipments", ["status"])
    op.create_table(
        "shipment_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "shipment_id",
            sa.Integer(),
            sa.ForeignKey("shipments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "allocation_id",
            sa.Integer(),
            sa.ForeignKey("inventory_allocations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_shipment_items_quantity_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shipment_id", "allocation_id", name="uq_shipment_allocation"),
    )
    op.create_index("ix_shipment_items_shipment_id", "shipment_items", ["shipment_id"])
    op.create_index("ix_shipment_items_allocation_id", "shipment_items", ["allocation_id"])

    op.add_column("payments", sa.Column("principal_subject", sa.String(255)))
    op.add_column("payments", sa.Column("request_fingerprint", sa.String(64)))
    op.add_column(
        "payments", sa.Column("reconciliation_deadline_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "payments",
        sa.Column("reconciliation_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_index(
        "ix_payments_reconciliation_deadline_at", "payments", ["reconciliation_deadline_at"]
    )

    op.create_table(
        "refunds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "payment_id",
            sa.Integer(),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("provider_idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("provider_reference", sa.String(255), unique=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(24), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("review_reason", sa.String(500)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id", "idempotency_key", name="uq_refund_payment_key"),
    )
    op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"])
    op.create_index("ix_refunds_status", "refunds", ["status"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])
    op.create_index("ix_outbox_events_available_at", "outbox_events", ["available_at"])
    op.create_index("ix_outbox_events_published_at", "outbox_events", ["published_at"])
    op.create_index(
        "ix_outbox_events_dead_lettered_at", "outbox_events", ["dead_lettered_at"]
    )

    op.create_table(
        "webhook_inbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("event_id", sa.String(255), nullable=False, unique=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_inbox_event_id", "webhook_inbox", ["event_id"])
    op.create_table(
        "simulator_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("provider_reference", sa.String(255), nullable=False, unique=True),
        sa.Column("operation", sa.String(24), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_simulator_transactions_idempotency_key",
        "simulator_transactions",
        ["idempotency_key"],
    )


def downgrade() -> None:
    raise NotImplementedError(
        "This data migration is intentionally irreversible; restore a verified backup instead."
    )
