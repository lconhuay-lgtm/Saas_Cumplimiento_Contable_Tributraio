"""Cronograma: columna tipo (mensual|sire) para soportar el cronograma SIRE

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cronograma_vencimientos",
        sa.Column("tipo", sa.String(length=20), nullable=False, server_default="mensual"),
    )
    op.alter_column("cronograma_vencimientos", "tipo", server_default=None)
    op.drop_constraint("uq_cronograma_periodo_grupo", "cronograma_vencimientos", type_="unique")
    op.create_unique_constraint(
        "uq_cronograma_periodo_grupo_tipo", "cronograma_vencimientos", ["periodo_tributario", "grupo", "tipo"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_cronograma_periodo_grupo_tipo", "cronograma_vencimientos", type_="unique")
    op.create_unique_constraint(
        "uq_cronograma_periodo_grupo", "cronograma_vencimientos", ["periodo_tributario", "grupo"]
    )
    op.drop_column("cronograma_vencimientos", "tipo")
