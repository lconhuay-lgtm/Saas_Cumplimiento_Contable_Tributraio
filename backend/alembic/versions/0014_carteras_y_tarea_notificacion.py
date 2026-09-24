"""Carteras (Empresa.asignado_a_usuario_id) + tarea desde notificacion (TareaObligacion.mensaje_buzon_id)

Dos columnas nuevas, empaquetadas juntas porque se pidieron en el mismo lote
de trabajo:
- empresas.asignado_a_usuario_id: que usuario del tenant sigue esta empresa
  (un dueno por empresa, nullable -- "sin asignar" es un estado valido).
- tarea_obligaciones.mensaje_buzon_id: de que notificacion del buzon nacio
  esta tarea, si nacio de una (nullable -- las tareas del cronograma/
  obligaciones recurrentes o las sueltas creadas a mano siguen sin esto).
  Unique: una notificacion genera como maximo una tarea.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "empresas",
        sa.Column("asignado_a_usuario_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=True),
    )
    op.create_index("ix_empresas_asignado_a_usuario_id", "empresas", ["asignado_a_usuario_id"])

    op.add_column(
        "tarea_obligaciones",
        sa.Column("mensaje_buzon_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("mensajes_buzon.id"), nullable=True),
    )
    op.create_unique_constraint(
        "uq_tarea_obligacion_mensaje_buzon", "tarea_obligaciones", ["mensaje_buzon_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_tarea_obligacion_mensaje_buzon", "tarea_obligaciones", type_="unique")
    op.drop_column("tarea_obligaciones", "mensaje_buzon_id")

    op.drop_index("ix_empresas_asignado_a_usuario_id", table_name="empresas")
    op.drop_column("empresas", "asignado_a_usuario_id")
