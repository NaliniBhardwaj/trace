"""phase4.1 operational assignments

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-26
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_assignments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("zone_id", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "ACTIVE", "COMPLETED", "CANCELLED", name="assignmentstatus"),
            nullable=True,
        ),
        sa.Column("rotation_id", sa.String(), nullable=True),
        sa.Column("assigned_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"]),
        sa.ForeignKeyConstraint(["rotation_id"], ["rotation_recommendations.id"]),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operational_assignments_worker", "operational_assignments", ["worker_id"])
    op.create_index("ix_operational_assignments_zone", "operational_assignments", ["zone_id"])
    op.create_index("ix_operational_assignments_status", "operational_assignments", ["status"])


def downgrade() -> None:
    op.drop_index("ix_operational_assignments_status", table_name="operational_assignments")
    op.drop_index("ix_operational_assignments_zone", table_name="operational_assignments")
    op.drop_index("ix_operational_assignments_worker", table_name="operational_assignments")
    op.drop_table("operational_assignments")
