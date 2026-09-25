"""Obligacion: prioridad por defecto de las tareas que genera

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "empresa_obligaciones",
        sa.Column("prioridad", sa.String(length=20), nullable=False, server_default="media"),
    )
    op.alter_column("empresa_obligaciones", "prioridad", server_default=None)


def downgrade() -> None:
    op.drop_column("empresa_obligaciones", "prioridad")
