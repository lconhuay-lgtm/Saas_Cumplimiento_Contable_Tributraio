"""Modulo de Tareas/Agenda: empresa_obligaciones + tarea_obligaciones

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "empresa_obligaciones",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("tipo", sa.String(30), nullable=False),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("regla_vencimiento", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("dia_fijo", sa.Integer(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "tipo", "nombre", name="uq_empresa_obligacion_tipo_nombre"),
    )
    op.create_index("ix_empresa_obligaciones_empresa_id", "empresa_obligaciones", ["empresa_id"])

    op.create_table(
        "tarea_obligaciones",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("empresa_obligacion_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresa_obligaciones.id"), nullable=True),
        sa.Column("titulo", sa.String(300), nullable=False),
        sa.Column("tipo", sa.String(30), nullable=False),
        sa.Column("periodo", sa.String(7), nullable=True),
        sa.Column("fecha_vencimiento", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("prioridad", sa.String(20), nullable=False, server_default="media"),
        sa.Column("proceso", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("fecha_completado", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observaciones", sa.String(2000), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_obligacion_id", "periodo", name="uq_tarea_obligacion_periodo"),
    )
    op.create_index("ix_tarea_obligaciones_empresa_id", "tarea_obligaciones", ["empresa_id"])
    op.create_index("ix_tarea_obligaciones_empresa_obligacion_id", "tarea_obligaciones", ["empresa_obligacion_id"])
    op.create_index("ix_tarea_obligaciones_estado", "tarea_obligaciones", ["estado"])
    op.create_index("ix_tarea_obligaciones_fecha_vencimiento", "tarea_obligaciones", ["fecha_vencimiento"])


def downgrade() -> None:
    op.drop_index("ix_tarea_obligaciones_fecha_vencimiento", table_name="tarea_obligaciones")
    op.drop_index("ix_tarea_obligaciones_estado", table_name="tarea_obligaciones")
    op.drop_index("ix_tarea_obligaciones_empresa_obligacion_id", table_name="tarea_obligaciones")
    op.drop_index("ix_tarea_obligaciones_empresa_id", table_name="tarea_obligaciones")
    op.drop_table("tarea_obligaciones")

    op.drop_index("ix_empresa_obligaciones_empresa_id", table_name="empresa_obligaciones")
    op.drop_table("empresa_obligaciones")
