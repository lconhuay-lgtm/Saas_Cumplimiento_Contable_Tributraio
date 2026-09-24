"""Modulo de cronograma SUNAT: es_buen_contribuyente en empresas + tabla cronograma_vencimientos

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "empresas",
        sa.Column("es_buen_contribuyente", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "cronograma_vencimientos",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("periodo_tributario", sa.String(7), nullable=False),
        sa.Column("grupo", sa.String(30), nullable=False),
        sa.Column("fecha_vencimiento", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("periodo_tributario", "grupo", name="uq_cronograma_periodo_grupo"),
    )
    op.create_index("ix_cronograma_vencimientos_periodo_tributario", "cronograma_vencimientos", ["periodo_tributario"])
    op.create_index("ix_cronograma_vencimientos_fecha_vencimiento", "cronograma_vencimientos", ["fecha_vencimiento"])


def downgrade() -> None:
    op.drop_index("ix_cronograma_vencimientos_fecha_vencimiento", table_name="cronograma_vencimientos")
    op.drop_index("ix_cronograma_vencimientos_periodo_tributario", table_name="cronograma_vencimientos")
    op.drop_table("cronograma_vencimientos")
    op.drop_column("empresas", "es_buen_contribuyente")
