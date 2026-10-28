"""Liquidacion en vivo (piloto de octubre 2026): lecturas, 0621, SIRE, retenciones y percepciones, cuenta de control, calculos y conciliacion

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-28

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def _empresa():
    return sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False, index=True)


def _monto(nombre):
    return sa.Column(nombre, sa.Float(), nullable=False, server_default="0")


def upgrade() -> None:
    op.create_table(
        "liquidacion_lecturas",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        _empresa(),
        sa.Column("solicitado_por", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("fuente", sa.String(20), nullable=False),
        sa.Column("periodo_desde", sa.String(7), nullable=True),
        sa.Column("periodo_hasta", sa.String(7), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente", index=True),
        sa.Column("etapa", sa.String(30), nullable=True),
        sa.Column("registros_leidos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(1000), nullable=True),
    )
    op.create_table(
        "liquidacion_declaraciones",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        _empresa(),
        sa.Column("periodo", sa.String(7), nullable=False, index=True),
        sa.Column("num_orden", sa.String(20), nullable=False),
        sa.Column("rectificatoria", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fecha_presentacion", sa.Date(), nullable=True),
        sa.Column("casillas", sa.JSON(), nullable=False),
        sa.Column("vigente", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("leido_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "num_orden", name="uq_liq_declaracion_empresa_orden"),
    )
    op.create_table(
        "liquidacion_comprobantes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        _empresa(),
        sa.Column("periodo", sa.String(7), nullable=False, index=True),
        sa.Column("libro", sa.String(4), nullable=False),
        sa.Column("fuente", sa.String(12), nullable=False),
        sa.Column("car_sunat", sa.String(40), nullable=False),
        sa.Column("fecha_emision", sa.Date(), nullable=True),
        sa.Column("tipo_comprobante", sa.String(4), nullable=False, server_default=""),
        sa.Column("serie", sa.String(20), nullable=False, server_default=""),
        sa.Column("numero", sa.String(20), nullable=False, server_default=""),
        sa.Column("doc_contraparte", sa.String(15), nullable=False, server_default=""),
        sa.Column("nombre_contraparte", sa.String(200), nullable=False, server_default=""),
        _monto("base_gravada"),
        _monto("igv"),
        _monto("descuento_base"),
        _monto("descuento_igv"),
        _monto("base_dgng"),
        _monto("igv_dgng"),
        _monto("no_gravado"),
        _monto("exportacion"),
        _monto("total"),
        sa.Column("moneda", sa.String(3), nullable=False, server_default="PEN"),
        sa.Column("detraccion", sa.String(40), nullable=False, server_default=""),
        sa.Column("dam", sa.String(40), nullable=False, server_default=""),
        sa.Column("datos", sa.JSON(), nullable=False),
        sa.Column("leido_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "libro", "fuente", "car_sunat", name="uq_liq_comprobante_empresa_libro_fuente_car"),
    )
    op.create_table(
        "liquidacion_retenciones_percepciones",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        _empresa(),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("origen", sa.String(12), nullable=False),
        sa.Column("ruc_agente", sa.String(15), nullable=False, server_default=""),
        sa.Column("documento", sa.String(40), nullable=False),
        sa.Column("periodo", sa.String(7), nullable=False, index=True),
        sa.Column("fecha_emision", sa.Date(), nullable=True),
        sa.Column("fecha_pago", sa.Date(), nullable=True),
        _monto("monto"),
        sa.Column("cuenta", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("referencia", sa.String(40), nullable=False, server_default=""),
        sa.Column("leido_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "tipo", "origen", "ruc_agente", "documento", name="uq_liq_retper_empresa_documento"),
    )
    op.create_table(
        "liquidacion_cuenta_control",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        _empresa(),
        sa.Column("periodo", sa.String(7), nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("ruc_agente", sa.String(15), nullable=False, server_default=""),
        _monto("monto_base"),
        _monto("monto"),
        sa.Column("leido_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "periodo", "tipo", "ruc_agente", name="uq_liq_cuenta_control"),
    )
    op.create_table(
        "liquidacion_calculos",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        _empresa(),
        sa.Column("periodo", sa.String(7), nullable=False, index=True),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("casillas", sa.JSON(), nullable=False),
        sa.Column("fuentes", sa.JSON(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "periodo", "fecha", name="uq_liq_calculo_empresa_periodo_fecha"),
    )
    op.create_table(
        "liquidacion_conciliaciones",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        _empresa(),
        sa.Column("periodo", sa.String(7), nullable=False, index=True),
        sa.Column("num_orden", sa.String(20), nullable=False),
        sa.Column("casilla", sa.String(5), nullable=False),
        _monto("estimado"),
        _monto("declarado"),
        sa.Column("explicada", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("comentario", sa.String(500), nullable=True),
        sa.Column("explicada_por_usuario_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("explicada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "num_orden", "casilla", name="uq_liq_conciliacion_orden_casilla"),
    )


def downgrade() -> None:
    for tabla in (
        "liquidacion_conciliaciones", "liquidacion_calculos", "liquidacion_cuenta_control",
        "liquidacion_retenciones_percepciones", "liquidacion_comprobantes", "liquidacion_declaraciones",
        "liquidacion_lecturas",
    ):
        op.drop_table(tabla)
