"""Recibos por honorarios recibidos por cada empresa y sus lecturas (obligacion PLAME)

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-05

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def _uuid(nombre, **kw):
    return sa.Column(nombre, postgresql.UUID(as_uuid=False), **kw)


def upgrade() -> None:
    op.create_table(
        "consulta_rxh_jobs",
        _uuid("id", primary_key=True),
        _uuid("empresa_id", sa.ForeignKey("empresas.id"), nullable=False, index=True),
        _uuid("solicitado_por", sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("periodo", sa.String(7), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente", index=True),
        sa.Column("etapa", sa.String(30), nullable=True),
        sa.Column("recibos_leidos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
    )
    op.create_table(
        "recibos_honorarios",
        _uuid("id", primary_key=True),
        _uuid("empresa_id", sa.ForeignKey("empresas.id"), nullable=False, index=True),
        sa.Column("periodo", sa.String(7), nullable=False, index=True),
        sa.Column("fecha_emision", sa.Date(), nullable=True),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("numero", sa.String(30), nullable=False),
        sa.Column("estado", sa.String(30), nullable=False),
        sa.Column("doc_emisor", sa.String(15), nullable=False),
        sa.Column("nombre_emisor", sa.String(200), nullable=False, server_default=""),
        sa.Column("moneda", sa.String(20), nullable=False, server_default=""),
        sa.Column("renta_bruta", sa.Float(), nullable=False, server_default="0"),
        sa.Column("retencion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("renta_neta", sa.Float(), nullable=False, server_default="0"),
        sa.Column("pendiente_pago", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "doc_emisor", "tipo", "numero", name="uq_recibo_honorario"),
    )


def downgrade() -> None:
    op.drop_table("recibos_honorarios")
    op.drop_table("consulta_rxh_jobs")
