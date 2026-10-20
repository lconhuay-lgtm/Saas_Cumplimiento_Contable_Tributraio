"""SIRE: estado de presentacion por periodo (RVIE/RCE) + bitacora de consultas

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consulta_sire_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("solicitado_por", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("etapa", sa.String(30), nullable=True),
        sa.Column("periodos_actualizados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
    )
    op.create_index("ix_consulta_sire_jobs_empresa_id", "consulta_sire_jobs", ["empresa_id"])
    op.create_index("ix_consulta_sire_jobs_estado", "consulta_sire_jobs", ["estado"])

    op.create_table(
        "sire_estados_periodo",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("libro", sa.String(10), nullable=False),
        sa.Column("periodo", sa.String(7), nullable=False),
        sa.Column("cod_estado", sa.String(5), nullable=False),
        sa.Column("des_estado", sa.String(60), nullable=False),
        sa.Column("presentado", sa.Boolean(), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "libro", "periodo", name="uq_sire_estado_empresa_libro_periodo"),
    )
    op.create_index("ix_sire_estados_periodo_empresa_id", "sire_estados_periodo", ["empresa_id"])


def downgrade() -> None:
    op.drop_index("ix_sire_estados_periodo_empresa_id", table_name="sire_estados_periodo")
    op.drop_table("sire_estados_periodo")
    op.drop_index("ix_consulta_sire_jobs_estado", table_name="consulta_sire_jobs")
    op.drop_index("ix_consulta_sire_jobs_empresa_id", table_name="consulta_sire_jobs")
    op.drop_table("consulta_sire_jobs")
