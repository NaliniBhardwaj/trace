"""phase18 sos training gate and shift handover

Revision ID: l2a3b4c5d6e7
Revises: k1f2a3b4c5d6

Note: chained after the last migration that actually exists in this repo
(k1f2a3b4c5d6, Phase 8). Phases 9-17 (rotation AI, WhatsApp, intelligence,
reports, etc.) were developed SQLite-first via Base.metadata.create_all and
never got their own Alembic migrations, so a Postgres deployment was
already behind those tables before this change. This migration only adds
what Phase 18 introduces; it does not attempt to backfill phases 9-17.

SOS/panic-button alerts intentionally reuse the existing `alerts` table
(Alert.alert_type is a free-text String column) so no migration is needed
for that feature.
"""
from alembic import op
import sqlalchemy as sa

revision = "l2a3b4c5d6e7"
down_revision = "k1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workers", sa.Column("training_cert_name", sa.String(), nullable=True))
    op.add_column("workers", sa.Column("training_cert_expires_at", sa.DateTime(), nullable=True))

    op.create_table(
        "shift_handovers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("zone_id", sa.String(), nullable=False),
        sa.Column("from_user_id", sa.String(), nullable=False),
        sa.Column("to_user_id", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status_snapshot", sa.JSON(), nullable=True),
        sa.Column("acknowledged", sa.Boolean(), nullable=True),
        sa.Column("acknowledged_by", sa.String(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"]),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shift_handovers_zone", "shift_handovers", ["zone_id"])
    op.create_index("ix_shift_handovers_created", "shift_handovers", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_shift_handovers_created", table_name="shift_handovers")
    op.drop_index("ix_shift_handovers_zone", table_name="shift_handovers")
    op.drop_table("shift_handovers")
    op.drop_column("workers", "training_cert_expires_at")
    op.drop_column("workers", "training_cert_name")
