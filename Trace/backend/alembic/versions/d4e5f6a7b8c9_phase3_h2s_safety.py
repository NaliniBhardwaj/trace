"""phase3 h2s reading + exposure interval fields

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "h2s_readings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("zone_id", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("h2s_ppm", sa.Float(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("SYNTHETIC", "STRIP_ML", "SENSOR", name="h2ssource"),
            nullable=False,
        ),
        sa.Column("is_synthetic", sa.Boolean(), nullable=True),
        sa.Column("client_reading_uuid", sa.String(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"]),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_h2s_readings_zone_id", "h2s_readings", ["zone_id"])
    op.create_index("ix_h2s_readings_worker_id", "h2s_readings", ["worker_id"])
    op.create_index("ix_h2s_readings_occurred_at", "h2s_readings", ["occurred_at"])
    op.create_index("ix_h2s_readings_client_uuid", "h2s_readings", ["client_reading_uuid"], unique=True)

    with op.batch_alter_table("exposure_events") as batch_op:
        batch_op.add_column(sa.Column("reading_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("start_time", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("end_time", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("duration_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("average_h2s_ppm", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("peak_h2s_ppm", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("exposure_dose_ppm_min", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("source", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("is_synthetic", sa.Boolean(), nullable=True, server_default=sa.text("0")))
        batch_op.create_foreign_key("fk_exposure_reading", "h2s_readings", ["reading_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("exposure_events") as batch_op:
        batch_op.drop_constraint("fk_exposure_reading", type_="foreignkey")
        batch_op.drop_column("is_synthetic")
        batch_op.drop_column("source")
        batch_op.drop_column("exposure_dose_ppm_min")
        batch_op.drop_column("peak_h2s_ppm")
        batch_op.drop_column("average_h2s_ppm")
        batch_op.drop_column("duration_seconds")
        batch_op.drop_column("end_time")
        batch_op.drop_column("start_time")
        batch_op.drop_column("reading_id")
    op.drop_index("ix_h2s_readings_client_uuid", table_name="h2s_readings")
    op.drop_index("ix_h2s_readings_occurred_at", table_name="h2s_readings")
    op.drop_index("ix_h2s_readings_worker_id", table_name="h2s_readings")
    op.drop_index("ix_h2s_readings_zone_id", table_name="h2s_readings")
    op.drop_table("h2s_readings")
