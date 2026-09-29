"""phase7 permit to enter

Revision ID: i9d0e1f2a3b4
Revises: h8c9d0e1f2a3
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = "i9d0e1f2a3b4"
down_revision = "h8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "permits_to_enter",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("permit_code", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("zone_id", sa.String(), nullable=False),
        sa.Column("issued_by", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "REQUESTED", "APPROVED", "ACTIVE", "EXPIRED", "SUSPENDED",
                "REVOKED", "COMPLETED", "DENIED",
                name="permitstatus",
            ),
            nullable=True,
        ),
        sa.Column("purpose", sa.String(), nullable=True),
        sa.Column("decision_reason", sa.String(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("denial_reason", sa.String(), nullable=True),
        sa.Column("qr_payload", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"]),
        sa.ForeignKeyConstraint(["issued_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("permit_code"),
    )
    op.create_index("ix_permits_worker", "permits_to_enter", ["worker_id"])
    op.create_index("ix_permits_zone", "permits_to_enter", ["zone_id"])
    op.create_index("ix_permits_status", "permits_to_enter", ["status"])
    op.create_index("ix_permits_code", "permits_to_enter", ["permit_code"])


def downgrade() -> None:
    op.drop_index("ix_permits_code", table_name="permits_to_enter")
    op.drop_index("ix_permits_status", table_name="permits_to_enter")
    op.drop_index("ix_permits_zone", table_name="permits_to_enter")
    op.drop_index("ix_permits_worker", table_name="permits_to_enter")
    op.drop_table("permits_to_enter")
