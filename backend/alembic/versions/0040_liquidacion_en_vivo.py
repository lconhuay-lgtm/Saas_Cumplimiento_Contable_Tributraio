"""Liquidacion en vivo (Etapa 1): activacion por empresa, API del SIRE y registro de cambios

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("liquidacion_incluidas", sa.Integer(), nullable=False, server_default="15"))
    op.create_table(
        "liquidacion_empresas",
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), primary_key=True),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("activada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activada_por_usuario_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("regimen", sa.String(20), nullable=True),
        sa.Column("regimen_origen", sa.String(10), nullable=True),
        sa.Column("api_client_id", sa.String(100), nullable=True),
        sa.Column("api_secret_cifrado", sa.LargeBinary(), nullable=True),
        sa.Column("api_dek_cifrada", sa.LargeBinary(), nullable=True),
        sa.Column("api_estado", sa.String(20), nullable=False, server_default="sin_configurar"),
        sa.Column("api_mensaje", sa.String(500), nullable=True),
        sa.Column("api_probado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sire_periodos", sa.Integer(), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "liquidacion_eventos",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False, index=True),
        sa.Column("usuario_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("accion", sa.String(40), nullable=False),
        sa.Column("detalle", sa.String(500), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("liquidacion_eventos")
    op.drop_table("liquidacion_empresas")
    op.drop_column("tenants", "liquidacion_incluidas")
