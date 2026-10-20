"""Deudas: valores pendientes de pago (con historial) + bitacora de consultas

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consulta_deudas_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("solicitado_por", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("etapa", sa.String(30), nullable=True),
        sa.Column("valores_vigentes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valores_nuevos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
    )
    op.create_index("ix_consulta_deudas_jobs_empresa_id", "consulta_deudas_jobs", ["empresa_id"])
    op.create_index("ix_consulta_deudas_jobs_estado", "consulta_deudas_jobs", ["estado"])

    op.create_table(
        "valores_deuda",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("num_valor", sa.String(20), nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False, server_default=""),
        sa.Column("tipo_descripcion", sa.String(80), nullable=False, server_default=""),
        sa.Column("periodo", sa.String(7), nullable=False, server_default=""),
        sa.Column("cod_tributo", sa.String(10), nullable=False, server_default=""),
        sa.Column("tributo", sa.String(150), nullable=False, server_default=""),
        sa.Column("fecha_emision", sa.Date(), nullable=True),
        sa.Column("fecha_notificacion", sa.Date(), nullable=True),
        sa.Column("estado", sa.String(60), nullable=False, server_default=""),
        sa.Column("etapa_cod", sa.String(5), nullable=False, server_default=""),
        sa.Column("etapa", sa.String(80), nullable=False, server_default=""),
        sa.Column("etapa_alterna", sa.String(80), nullable=False, server_default=""),
        sa.Column("en_cobranza_coactiva", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("num_expediente_coactivo", sa.String(25), nullable=True),
        sa.Column("monto_tributo", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tributo_pendiente", sa.Float(), nullable=False, server_default="0"),
        sa.Column("interes", sa.Float(), nullable=False, server_default="0"),
        sa.Column("saldo_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("saldo_exigible", sa.Float(), nullable=False, server_default="0"),
        sa.Column("vigente", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("detectado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("visto_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ya_no_aparece_desde", sa.DateTime(timezone=True), nullable=True),
        sa.Column("historial", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("notificado_popup", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("empresa_id", "num_valor", name="uq_valor_deuda_empresa_numero"),
    )
    op.create_index("ix_valores_deuda_empresa_id", "valores_deuda", ["empresa_id"])
    op.create_index("ix_valores_deuda_vigente", "valores_deuda", ["vigente"])


def downgrade() -> None:
    op.drop_index("ix_valores_deuda_vigente", table_name="valores_deuda")
    op.drop_index("ix_valores_deuda_empresa_id", table_name="valores_deuda")
    op.drop_table("valores_deuda")
    op.drop_index("ix_consulta_deudas_jobs_estado", table_name="consulta_deudas_jobs")
    op.drop_index("ix_consulta_deudas_jobs_empresa_id", table_name="consulta_deudas_jobs")
    op.drop_table("consulta_deudas_jobs")
