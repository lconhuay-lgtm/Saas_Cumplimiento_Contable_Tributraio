"""agrega nombre y apellidos a usuarios (pestana Perfil del menu de cuenta)

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("nombre", sa.String(length=100), nullable=True))
    op.add_column("usuarios", sa.Column("apellidos", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("usuarios", "apellidos")
    op.drop_column("usuarios", "nombre")
