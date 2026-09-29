"""phase1 worker zone infrastructure

Revision ID: b1c2d3e4f5a6
Revises: a44f0b8d830b
Create Date: 2026-09-26 00:00:00.000000

Phase 1: extend workers and zones with operational fields;
add ADMIN role and NORMAL risk level; WorkerStatus enum.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a44f0b8d830b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enum extensions (SQLite stores enums as VARCHAR; recreate is safe) ---
    # RoleEnum: add ADMIN. RiskLevel: add NORMAL. WorkerStatus: new enum.

    with op.batch_alter_table("workers") as batch_op:
        batch_op.add_column(sa.Column("employee_code", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("department", sa.String(), nullable=True, server_default="Operations"))
        batch_op.add_column(sa.Column("phone", sa.String(), nullable=True, server_default=""))
        batch_op.add_column(
            sa.Column(
                "status",
                sa.Enum("ACTIVE", "OFF_SHIFT", "UNAVAILABLE", "SUSPENDED", name="workerstatus"),
                nullable=True,
                server_default="ACTIVE",
            )
        )
        batch_op.add_column(sa.Column("is_synthetic", sa.Boolean(), nullable=True, server_default=sa.text("1")))
        batch_op.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_workers_employee_code", ["employee_code"], unique=True)

    with op.batch_alter_table("zones") as batch_op:
        batch_op.add_column(sa.Column("zone_type", sa.String(), nullable=True, server_default="OPERATIONAL"))
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True, server_default=""))
        batch_op.add_column(
            sa.Column(
                "risk_level",
                sa.Enum("LOW", "NORMAL", "ELEVATED", "HIGH", "CRITICAL", name="risklevel"),
                nullable=True,
                server_default="NORMAL",
            )
        )
        batch_op.add_column(sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("1")))
        batch_op.add_column(sa.Column("adjacent_zone_ids", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("is_synthetic", sa.Boolean(), nullable=True, server_default=sa.text("1")))
        batch_op.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))

    # RoleEnum ADMIN: SQLite stores as string — no ALTER TYPE needed.
    # Existing role column accepts any string; models define ADMIN.


def downgrade() -> None:
    with op.batch_alter_table("zones") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("created_at")
        batch_op.drop_column("is_synthetic")
        batch_op.drop_column("adjacent_zone_ids")
        batch_op.drop_column("is_active")
        batch_op.drop_column("risk_level")
        batch_op.drop_column("description")
        batch_op.drop_column("zone_type")

    with op.batch_alter_table("workers") as batch_op:
        batch_op.drop_index("ix_workers_employee_code")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("created_at")
        batch_op.drop_column("is_synthetic")
        batch_op.drop_column("status")
        batch_op.drop_column("phone")
        batch_op.drop_column("department")
        batch_op.drop_column("employee_code")
