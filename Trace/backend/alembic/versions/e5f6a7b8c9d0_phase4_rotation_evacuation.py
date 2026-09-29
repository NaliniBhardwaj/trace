"""phase4 rotation recommendations + evacuation events

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-26

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rotation_policies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("dose_threshold_ppm_min", sa.Float(), nullable=False),
        sa.Column("continuous_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("min_rest_seconds", sa.Integer(), nullable=False),
        sa.Column("require_same_department", sa.Boolean(), nullable=True),
        sa.Column("trigger_risk_levels", sa.JSON(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rotation_recommendations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_worker_id", sa.String(), nullable=False),
        sa.Column("replacement_worker_id", sa.String(), nullable=True),
        sa.Column("zone_id", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source_risk_level", sa.String(), nullable=True),
        sa.Column("source_exposure_ppm_min", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "CONFIRMED", "REJECTED", "CANCELLED", "BLOCKED", "ACTIVE", "COMPLETED", name="rotationstatus"),
            nullable=True,
        ),
        sa.Column("confirmed_by", sa.String(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("policy_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_worker_id"], ["workers.id"]),
        sa.ForeignKeyConstraint(["replacement_worker_id"], ["workers.id"]),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"]),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["policy_id"], ["rotation_policies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rotation_recommendations_source", "rotation_recommendations", ["source_worker_id"])
    op.create_index("ix_rotation_recommendations_status", "rotation_recommendations", ["status"])

    op.create_table(
        "evacuation_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("zone_id", sa.String(), nullable=False),
        sa.Column("risk_level", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("OPEN", "ACKNOWLEDGED", "RESOLVED", "CANCELLED", name="evacuationstatus"),
            nullable=True,
        ),
        sa.Column("acknowledged_by", sa.String(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"]),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evacuation_events_worker", "evacuation_events", ["worker_id"])
    op.create_index("ix_evacuation_events_zone", "evacuation_events", ["zone_id"])
    op.create_index("ix_evacuation_events_status", "evacuation_events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_evacuation_events_status", table_name="evacuation_events")
    op.drop_index("ix_evacuation_events_zone", table_name="evacuation_events")
    op.drop_index("ix_evacuation_events_worker", table_name="evacuation_events")
    op.drop_table("evacuation_events")
    op.drop_index("ix_rotation_recommendations_status", table_name="rotation_recommendations")
    op.drop_index("ix_rotation_recommendations_source", table_name="rotation_recommendations")
    op.drop_table("rotation_recommendations")
    op.drop_table("rotation_policies")
