"""Detracciones: historial desde 2022 con marca de avance por empresa

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "consulta_detracciones_jobs",
        sa.Column("modo", sa.String(20), nullable=False, server_default="manual"),
    )
    op.create_table(
        "detracciones_cobertura",
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), primary_key=True),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date(), nullable=False),
        sa.Column("carga_completa", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("detracciones_cobertura")
    op.drop_column("consulta_detracciones_jobs", "modo")
