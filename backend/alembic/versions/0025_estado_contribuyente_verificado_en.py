"""agrega estado_contribuyente_verificado_en a empresas (batching diario del estado del contribuyente)

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "empresas",
        sa.Column("estado_contribuyente_verificado_en", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("empresas", "estado_contribuyente_verificado_en")
