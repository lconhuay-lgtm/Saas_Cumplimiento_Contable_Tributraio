"""Embargos notificados, REC y enlace de tareas con SUNAT (verificacion automatica y referencia)

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tarea_obligaciones", sa.Column("verificado_sunat_en", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tarea_obligaciones", sa.Column("referencia_sunat", sa.String(60), nullable=True))
    op.create_index("ix_tarea_obligaciones_referencia_sunat", "tarea_obligaciones", ["referencia_sunat"])
    op.add_column(
        "consulta_deudas_jobs",
        sa.Column("embargos_leidos", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "embargos_notificados",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("rc_embargo", sa.String(25), nullable=False),
        sa.Column("ruc_tercero", sa.String(15), nullable=False, server_default=""),
        sa.Column("nombre_tercero", sa.String(150), nullable=False, server_default=""),
        sa.Column("fecha_registro", sa.Date(), nullable=True),
        sa.Column("fecha_notificacion", sa.Date(), nullable=True),
        sa.Column("estado", sa.String(60), nullable=False, server_default=""),
        sa.Column("monto_embargado", sa.Float(), nullable=False, server_default="0"),
        sa.Column("monto_entregado", sa.Float(), nullable=False, server_default="0"),
        sa.Column("monto_pendiente", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rc_levantamiento", sa.String(25), nullable=True),
        sa.Column("fecha_levantamiento", sa.Date(), nullable=True),
        sa.Column("imposibilidad", sa.String(150), nullable=False, server_default=""),
        sa.Column("detectado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("visto_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "rc_embargo", name="uq_embargo_empresa_rc"),
    )
    op.create_index("ix_embargos_notificados_empresa_id", "embargos_notificados", ["empresa_id"])

    op.create_table(
        "recs_coactiva",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("num_rec", sa.String(25), nullable=False),
        sa.Column("dependencia", sa.String(120), nullable=False, server_default=""),
        sa.Column("estado", sa.String(60), nullable=False, server_default=""),
        sa.Column("fecha_emision", sa.Date(), nullable=True),
        sa.Column("fecha_notificacion", sa.Date(), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "num_rec", name="uq_rec_empresa_numero"),
    )
    op.create_index("ix_recs_coactiva_empresa_id", "recs_coactiva", ["empresa_id"])


def downgrade() -> None:
    op.drop_index("ix_recs_coactiva_empresa_id", table_name="recs_coactiva")
    op.drop_table("recs_coactiva")
    op.drop_index("ix_embargos_notificados_empresa_id", table_name="embargos_notificados")
    op.drop_table("embargos_notificados")
    op.drop_column("consulta_deudas_jobs", "embargos_leidos")
    op.drop_index("ix_tarea_obligaciones_referencia_sunat", table_name="tarea_obligaciones")
    op.drop_column("tarea_obligaciones", "referencia_sunat")
    op.drop_column("tarea_obligaciones", "verificado_sunat_en")
