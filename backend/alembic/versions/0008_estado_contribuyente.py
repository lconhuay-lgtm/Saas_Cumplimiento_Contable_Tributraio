"""agrega estado_contribuyente (+ anterior y fecha) a empresas

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("empresas", sa.Column("estado_contribuyente", sa.String(30), nullable=True))
    op.add_column("empresas", sa.Column("estado_contribuyente_anterior", sa.String(30), nullable=True))
    op.add_column("empresas", sa.Column("estado_contribuyente_actualizado_en", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("empresas", "estado_contribuyente_actualizado_en")
    op.drop_column("empresas", "estado_contribuyente_anterior")
    op.drop_column("empresas", "estado_contribuyente")
