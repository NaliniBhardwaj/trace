"""phase5 alerts extension + zone remediations

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = "g7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("alert_type", sa.String(), nullable=True))
    op.add_column("alerts", sa.Column("severity", sa.String(), nullable=True))
    op.add_column("alerts", sa.Column("status", sa.String(), nullable=True))
    op.add_column("alerts", sa.Column("reading_id", sa.String(), nullable=True))
    op.add_column("alerts", sa.Column("resolved_at", sa.DateTime(), nullable=True))
    op.add_column("alerts", sa.Column("resolved_by", sa.String(), nullable=True))
    op.create_index("ix_alerts_alert_type", "alerts", ["alert_type"])
    op.create_index("ix_alerts_status", "alerts", ["status"])

    op.create_table(
        "zone_remediations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("zone_id", sa.String(), nullable=False),
        sa.Column("trigger_alert_id", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("REQUIRED", "ACKNOWLEDGED", "IN_PROGRESS", "COMPLETED", "CANCELLED", name="remediationstatus"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_by", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("started_by", sa.String(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_by", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"]),
        sa.ForeignKeyConstraint(["trigger_alert_id"], ["alerts.id"]),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["started_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["completed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_zone_remediations_zone", "zone_remediations", ["zone_id"])
    op.create_index("ix_zone_remediations_status", "zone_remediations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_zone_remediations_status", table_name="zone_remediations")
    op.drop_index("ix_zone_remediations_zone", table_name="zone_remediations")
    op.drop_table("zone_remediations")
    op.drop_index("ix_alerts_status", table_name="alerts")
    op.drop_index("ix_alerts_alert_type", table_name="alerts")
    op.drop_column("alerts", "resolved_by")
    op.drop_column("alerts", "resolved_at")
    op.drop_column("alerts", "reading_id")
    op.drop_column("alerts", "status")
    op.drop_column("alerts", "severity")
    op.drop_column("alerts", "alert_type")
