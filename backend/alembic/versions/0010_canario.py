"""Fase 3: agrega es_canario a empresas + tabla canario_checks

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "empresas",
        sa.Column("es_canario", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "canario_checks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("ejecutado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("exito", sa.Boolean(), nullable=False),
        sa.Column("duracion_seg", sa.Float(), nullable=True),
        sa.Column("flujo_detectado", sa.String(20), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
    )
    op.create_index("ix_canario_checks_empresa_id", "canario_checks", ["empresa_id"])
    op.create_index("ix_canario_checks_ejecutado_en", "canario_checks", ["ejecutado_en"])
    op.create_index("ix_canario_checks_exito", "canario_checks", ["exito"])


def downgrade() -> None:
    op.drop_index("ix_canario_checks_exito", table_name="canario_checks")
    op.drop_index("ix_canario_checks_ejecutado_en", table_name="canario_checks")
    op.drop_index("ix_canario_checks_empresa_id", table_name="canario_checks")
    op.drop_table("canario_checks")
    op.drop_column("empresas", "es_canario")
