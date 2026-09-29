"""phase2 location: zone.beacon_id + worker_location_events

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-09-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("zones") as batch_op:
        batch_op.add_column(sa.Column("beacon_id", sa.String(), nullable=True))
        batch_op.create_index("ix_zones_beacon_id", ["beacon_id"], unique=True)

    op.create_table(
        "worker_location_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("previous_zone_id", sa.String(), nullable=True),
        sa.Column("new_zone_id", sa.String(), nullable=True),
        sa.Column("beacon_id", sa.String(), nullable=True),
        sa.Column("rssi", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "source",
            sa.Enum("REAL_BLE", "DEMO_BLE", "MANUAL", "SYSTEM", name="locationsource"),
            nullable=False,
        ),
        sa.Column("signal_strength", sa.String(), nullable=True),
        sa.Column(
            "sync_status",
            sa.Enum("SYNCED", "PENDING", "SYNC_FAILED", name="syncstatus", create_type=False),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
        sa.ForeignKeyConstraint(["previous_zone_id"], ["zones.id"]),
        sa.ForeignKeyConstraint(["new_zone_id"], ["zones.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_worker_location_events_worker_id", "worker_location_events", ["worker_id"])
    op.create_index("ix_worker_location_events_occurred_at", "worker_location_events", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_worker_location_events_occurred_at", table_name="worker_location_events")
    op.drop_index("ix_worker_location_events_worker_id", table_name="worker_location_events")
    op.drop_table("worker_location_events")
    with op.batch_alter_table("zones") as batch_op:
        batch_op.drop_index("ix_zones_beacon_id")
        batch_op.drop_column("beacon_id")
