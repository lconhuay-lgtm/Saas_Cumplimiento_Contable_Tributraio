"""agrega ficha_ruc_pdf_ref/ficha_ruc_generada_en a empresas + tabla ficha_ruc_jobs

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "empresas",
        sa.Column("ficha_ruc_pdf_ref", sa.String(500), nullable=True),
    )
    op.add_column(
        "empresas",
        sa.Column("ficha_ruc_generada_en", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "ficha_ruc_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("solicitado_por", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
    )
    op.create_index("ix_ficha_ruc_jobs_empresa_id", "ficha_ruc_jobs", ["empresa_id"])
    op.create_index("ix_ficha_ruc_jobs_estado", "ficha_ruc_jobs", ["estado"])


def downgrade() -> None:
    op.drop_index("ix_ficha_ruc_jobs_estado", table_name="ficha_ruc_jobs")
    op.drop_index("ix_ficha_ruc_jobs_empresa_id", table_name="ficha_ruc_jobs")
    op.drop_table("ficha_ruc_jobs")
    op.drop_column("empresas", "ficha_ruc_generada_en")
    op.drop_column("empresas", "ficha_ruc_pdf_ref")
