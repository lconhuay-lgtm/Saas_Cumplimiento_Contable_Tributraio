"""Reporte Tributario para Terceros (SUNAT lo envia por correo, sin PDF propio)

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reporte_tributario_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("solicitado_por", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("correo_destino", sa.String(255), nullable=False),
        sa.Column("etapa", sa.String(30), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
    )
    op.create_index("ix_reporte_tributario_jobs_empresa_id", "reporte_tributario_jobs", ["empresa_id"])
    op.create_index("ix_reporte_tributario_jobs_estado", "reporte_tributario_jobs", ["estado"])


def downgrade() -> None:
    op.drop_index("ix_reporte_tributario_jobs_estado", table_name="reporte_tributario_jobs")
    op.drop_index("ix_reporte_tributario_jobs_empresa_id", table_name="reporte_tributario_jobs")
    op.drop_table("reporte_tributario_jobs")
