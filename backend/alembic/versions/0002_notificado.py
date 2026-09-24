"""agrega columna notificado a consultas_jobs (Fase 2 -- resumen diario por correo)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "consultas_jobs",
        sa.Column("notificado", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("consultas_jobs", "notificado")
