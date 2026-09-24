"""Fase R2: separar staff de plataforma de usuarios de tenant

Agrega Usuario.es_staff_plataforma -- flag para el equipo operador,
distinto de `rol` (que es un permiso DENTRO de un tenant). Ver
backend/app/deps.py (get_staff_actual) y backend/app/routers/admin.py
para donde se usa.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usuarios",
        sa.Column("es_staff_plataforma", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("usuarios", "es_staff_plataforma")
