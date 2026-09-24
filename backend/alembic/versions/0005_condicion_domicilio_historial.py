"""agrega condicion_domicilio_anterior y condicion_domicilio_actualizada_en a empresas

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "empresas",
        sa.Column("condicion_domicilio_anterior", sa.String(20), nullable=True),
    )
    op.add_column(
        "empresas",
        sa.Column("condicion_domicilio_actualizada_en", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("empresas", "condicion_domicilio_actualizada_en")
    op.drop_column("empresas", "condicion_domicilio_anterior")
