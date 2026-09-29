"""phase7.1 permit suspension fields

Revision ID: j0e1f2a3b4c5
Revises: i9d0e1f2a3b4
"""
from alembic import op
import sqlalchemy as sa

revision = "j0e1f2a3b4c5"
down_revision = "i9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("permits_to_enter", sa.Column("suspended_at", sa.DateTime(), nullable=True))
    op.add_column("permits_to_enter", sa.Column("suspension_reason", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("permits_to_enter", "suspension_reason")
    op.drop_column("permits_to_enter", "suspended_at")
