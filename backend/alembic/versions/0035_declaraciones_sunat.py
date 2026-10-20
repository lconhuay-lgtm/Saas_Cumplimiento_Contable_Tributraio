"""Declaraciones y pagos presentados (Consulta general por periodo) + bitacora de consultas

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consulta_declaraciones_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("solicitado_por", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("etapa", sa.String(30), nullable=True),
        sa.Column("formularios_leidos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
    )
    op.create_index("ix_consulta_declaraciones_jobs_empresa_id", "consulta_declaraciones_jobs", ["empresa_id"])
    op.create_index("ix_consulta_declaraciones_jobs_estado", "consulta_declaraciones_jobs", ["estado"])

    op.create_table(
        "declaraciones_sunat",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("periodo", sa.String(7), nullable=False),
        sa.Column("formulario", sa.String(6), nullable=False),
        sa.Column("num_orden", sa.String(20), nullable=False),
        sa.Column("descripcion", sa.String(120), nullable=False, server_default=""),
        sa.Column("fecha_presentacion", sa.Date(), nullable=True),
        sa.Column("banco", sa.String(80), nullable=False, server_default=""),
        sa.Column("cod_tributo", sa.String(10), nullable=False, server_default=""),
        sa.Column("importe_pagado", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "formulario", "num_orden", "cod_tributo", name="uq_declaracion_empresa_form_orden"),
    )
    op.create_index("ix_declaraciones_sunat_empresa_id", "declaraciones_sunat", ["empresa_id"])
    op.create_index("ix_declaraciones_sunat_periodo", "declaraciones_sunat", ["periodo"])


def downgrade() -> None:
    op.drop_index("ix_declaraciones_sunat_periodo", table_name="declaraciones_sunat")
    op.drop_index("ix_declaraciones_sunat_empresa_id", table_name="declaraciones_sunat")
    op.drop_table("declaraciones_sunat")
    op.drop_index("ix_consulta_declaraciones_jobs_estado", table_name="consulta_declaraciones_jobs")
    op.drop_index("ix_consulta_declaraciones_jobs_empresa_id", table_name="consulta_declaraciones_jobs")
    op.drop_table("consulta_declaraciones_jobs")
