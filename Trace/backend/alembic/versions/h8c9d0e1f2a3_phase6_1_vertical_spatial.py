"""phase6.1 vertical spatial metadata on zones

Revision ID: h8c9d0e1f2a3
Revises: g7b8c9d0e1f2
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = "h8c9d0e1f2a3"
down_revision = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("zones", sa.Column("floor_level", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("zones", sa.Column("floor_label", sa.String(), nullable=True, server_default="GROUND"))
    op.add_column("zones", sa.Column("map_x", sa.Integer(), nullable=True))
    op.add_column("zones", sa.Column("map_y", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("zones", "map_y")
    op.drop_column("zones", "map_x")
    op.drop_column("zones", "floor_label")
    op.drop_column("zones", "floor_level")
