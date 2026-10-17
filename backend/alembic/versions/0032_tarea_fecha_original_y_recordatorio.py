"""tarea_obligaciones: fecha_vencimiento_original (deteccion de aplazadas) + recordatorio_enviado_en

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-17

"""
from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tarea_obligaciones",
        sa.Column("fecha_vencimiento_original", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill: para las tareas que ya existen, se usa su fecha_vencimiento
    # ACTUAL como linea base -- no sabemos cual fue su fecha "original" de
    # verdad (no se trackeaba hasta ahora), pero asi, si alguien la aplaza
    # de aqui en adelante, el cambio se detecta correctamente contra este
    # punto de partida.
    op.execute("UPDATE tarea_obligaciones SET fecha_vencimiento_original = fecha_vencimiento")

    # Cuando se mando el recordatorio por correo de "vence pronto" para
    # esta tarea -- None todavia no se envio. Se usa para no mandar el
    # mismo aviso todos los dias mientras siga pendiente dentro de la
    # ventana (ver scheduler_job.enviar_recordatorios_vencimiento).
    op.add_column(
        "tarea_obligaciones",
        sa.Column("recordatorio_enviado_en", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tarea_obligaciones", "recordatorio_enviado_en")
    op.drop_column("tarea_obligaciones", "fecha_vencimiento_original")
