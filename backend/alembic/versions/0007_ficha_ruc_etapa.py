"""agrega etapa a ficha_ruc_jobs (progreso mientras se genera el PDF)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ficha_ruc_jobs",
        sa.Column("etapa", sa.String(30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ficha_ruc_jobs", "etapa")
