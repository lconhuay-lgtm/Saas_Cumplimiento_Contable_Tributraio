"""agrega etapa a consultas_jobs (progreso de la consulta manual/automatica)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("consultas_jobs", sa.Column("etapa", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("consultas_jobs", "etapa")
