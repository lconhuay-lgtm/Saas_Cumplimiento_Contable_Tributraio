"""agrega condicion_domicilio a empresas (Habido/No Habido/No Hallado)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "empresas",
        sa.Column("condicion_domicilio", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("empresas", "condicion_domicilio")
