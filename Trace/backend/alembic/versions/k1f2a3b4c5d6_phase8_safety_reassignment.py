"""phase8 safety reassignment recommendations

Revision ID: k1f2a3b4c5d6
Revises: j0e1f2a3b4c5
"""
from alembic import op
import sqlalchemy as sa

revision = "k1f2a3b4c5d6"
down_revision = "j0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_reassignment_recommendations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("source_zone_id", sa.String(), nullable=False),
        sa.Column("destination_zone_id", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source_risk", sa.String(), nullable=True),
        sa.Column("destination_risk", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "CONFIRMED", "REJECTED", "BLOCKED", "CANCELLED", name="reassignmentstatus"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_by", sa.String(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("evacuation_event_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"]),
        sa.ForeignKeyConstraint(["source_zone_id"], ["zones.id"]),
        sa.ForeignKeyConstraint(["destination_zone_id"], ["zones.id"]),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["evacuation_event_id"], ["evacuation_events.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_safety_reassign_worker", "safety_reassignment_recommendations", ["worker_id"])
    op.create_index("ix_safety_reassign_status", "safety_reassignment_recommendations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_safety_reassign_status", table_name="safety_reassignment_recommendations")
    op.drop_index("ix_safety_reassign_worker", table_name="safety_reassignment_recommendations")
    op.drop_table("safety_reassignment_recommendations")
