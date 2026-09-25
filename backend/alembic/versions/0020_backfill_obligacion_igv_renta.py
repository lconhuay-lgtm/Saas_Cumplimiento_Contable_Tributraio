"""Backfill: obligacion IGV-Renta para empresas que existian antes de la Fase 1

Las empresas registradas ANTES de que existiera el checkbox "IGV-Renta"
en el alta (ver 0018 y app.routers.empresas._crear_obligaciones_por_defecto)
nunca recibieron esa EmpresaObligacion -- asi que aunque el cronograma
general de SUNAT si les aparece en el modulo Cronograma (viene directo de
Empresa + CronogramaVencimiento, no depende de las obligaciones), nunca se
les genera la TAREA de "declarar el impuesto" para hacer seguimiento de
cumplimiento. IGV-Renta le corresponde a practicamente cualquier empresa
activa, asi que este backfill se la agrega a las que todavia no la tengan.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-24

"""
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    empresas = conn.execute(sa.text("SELECT id FROM empresas")).fetchall()
    for (empresa_id,) in empresas:
        ya_tiene = conn.execute(
            sa.text("SELECT 1 FROM empresa_obligaciones WHERE empresa_id = :eid AND tipo = 'igv_renta'"),
            {"eid": empresa_id},
        ).first()
        if ya_tiene:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO empresa_obligaciones "
                "(id, empresa_id, tipo, nombre, activa, regla_vencimiento, creado_en) "
                "VALUES (:id, :empresa_id, 'igv_renta', 'IGV-Renta mensual', :activa, 'cronograma_sunat', :creado_en)"
            ),
            {
                "id": str(uuid.uuid4()),
                "empresa_id": empresa_id,
                "activa": True,
                "creado_en": datetime.now(timezone.utc),
            },
        )


def downgrade() -> None:
    # No se revierte -- no hay forma de distinguir una obligacion creada por
    # este backfill de una creada despues a mano por el usuario (o por el
    # alta normal de una empresa nueva en el mismo periodo), asi que borrar
    # por "tipo=igv_renta" en el downgrade se arriesgaria a borrar de mas.
    pass
