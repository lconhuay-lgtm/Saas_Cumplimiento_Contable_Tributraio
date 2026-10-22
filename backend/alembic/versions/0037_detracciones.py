"""Consulta de Pago de Detracciones: depositos SPOT + bitacora de busquedas

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consulta_detracciones_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("solicitado_por", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("etapa", sa.String(30), nullable=True),
        sa.Column("fecha_desde", sa.Date(), nullable=True),
        sa.Column("fecha_hasta", sa.Date(), nullable=True),
        sa.Column("periodo", sa.String(7), nullable=True),
        sa.Column("tipos_cuenta", sa.String(20), nullable=False, server_default="1"),
        sa.Column("tipos_pago", sa.String(80), nullable=False, server_default="pagosIndividuales"),
        sa.Column("depositos_leidos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
    )
    op.create_index("ix_consulta_detracciones_jobs_empresa_id", "consulta_detracciones_jobs", ["empresa_id"])
    op.create_index("ix_consulta_detracciones_jobs_estado", "consulta_detracciones_jobs", ["estado"])

    op.create_table(
        "detracciones_pagos",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("num_constancia", sa.String(40), nullable=False),
        sa.Column("tipo_cuenta", sa.String(2), nullable=False, server_default="1"),
        sa.Column("num_cuenta", sa.String(20), nullable=False, server_default=""),
        sa.Column("fecha_pago", sa.Date(), nullable=True),
        sa.Column("periodo", sa.String(7), nullable=False, server_default=""),
        sa.Column("tipo_comprobante", sa.String(4), nullable=False, server_default=""),
        sa.Column("serie", sa.String(10), nullable=False, server_default=""),
        sa.Column("numero", sa.String(20), nullable=False, server_default=""),
        sa.Column("ruc_proveedor", sa.String(15), nullable=False, server_default=""),
        sa.Column("proveedor", sa.String(200), nullable=False, server_default=""),
        sa.Column("tipo_doc_adquiriente", sa.String(4), nullable=False, server_default=""),
        sa.Column("doc_adquiriente", sa.String(15), nullable=False, server_default=""),
        sa.Column("adquiriente", sa.String(200), nullable=False, server_default=""),
        sa.Column("tipo_operacion", sa.String(4), nullable=False, server_default=""),
        sa.Column("tipo_bien", sa.String(4), nullable=False, server_default=""),
        sa.Column("monto", sa.Float(), nullable=False, server_default="0"),
        sa.Column("num_pago", sa.String(30), nullable=False, server_default=""),
        sa.Column("num_presentacion", sa.String(30), nullable=False, server_default=""),
        sa.Column("origen", sa.String(60), nullable=False, server_default=""),
        sa.Column("tipo_pago", sa.String(30), nullable=False, server_default="pagosIndividuales"),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "num_constancia", "tipo_cuenta", name="uq_detraccion_empresa_constancia"),
    )
    op.create_index("ix_detracciones_pagos_empresa_id", "detracciones_pagos", ["empresa_id"])
    op.create_index("ix_detracciones_pagos_fecha_pago", "detracciones_pagos", ["fecha_pago"])
    op.create_index("ix_detracciones_pagos_periodo", "detracciones_pagos", ["periodo"])


def downgrade() -> None:
    op.drop_index("ix_detracciones_pagos_periodo", table_name="detracciones_pagos")
    op.drop_index("ix_detracciones_pagos_fecha_pago", table_name="detracciones_pagos")
    op.drop_index("ix_detracciones_pagos_empresa_id", table_name="detracciones_pagos")
    op.drop_table("detracciones_pagos")
    op.drop_index("ix_consulta_detracciones_jobs_estado", table_name="consulta_detracciones_jobs")
    op.drop_index("ix_consulta_detracciones_jobs_empresa_id", table_name="consulta_detracciones_jobs")
    op.drop_table("consulta_detracciones_jobs")
