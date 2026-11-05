"""Revision de compras y credito fiscal (Fase 5): decisiones por compra y reglas por proveedor

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-05

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def _uuid(nombre, *args, **kw):
    return sa.Column(nombre, postgresql.UUID(as_uuid=False), *args, **kw)


def upgrade() -> None:
    op.create_table(
        "liquidacion_compras_decisiones",
        _uuid("id", primary_key=True),
        _uuid("empresa_id", sa.ForeignKey("empresas.id"), nullable=False, index=True),
        sa.Column("car_sunat", sa.String(40), nullable=False, index=True),
        sa.Column("periodo", sa.String(7), nullable=False),
        sa.Column("lleva", sa.String(10), nullable=False, server_default="auto"),
        sa.Column("credito", sa.String(10), nullable=False, server_default="auto"),
        sa.Column("motivo", sa.String(100), nullable=False, server_default=""),
        sa.Column("comentario", sa.String(500), nullable=False, server_default=""),
        sa.Column("constancia", sa.String(40), nullable=False, server_default=""),
        _uuid("usuario_id", sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "liquidacion_reglas_proveedor",
        _uuid("id", primary_key=True),
        _uuid("empresa_id", sa.ForeignKey("empresas.id"), nullable=False, index=True),
        sa.Column("ruc_proveedor", sa.String(15), nullable=False),
        sa.Column("nombre_proveedor", sa.String(200), nullable=False, server_default=""),
        sa.Column("regla", sa.String(20), nullable=False),
        sa.Column("desde_periodo", sa.String(7), nullable=False),
        sa.Column("motivo", sa.String(500), nullable=False, server_default=""),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        _uuid("usuario_id", sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _uuid("quitada_por_usuario_id", sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("quitada_en", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("liquidacion_reglas_proveedor")
    op.drop_table("liquidacion_compras_decisiones")
