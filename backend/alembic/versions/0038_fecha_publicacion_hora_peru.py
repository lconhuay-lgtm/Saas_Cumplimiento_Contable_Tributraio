"""La hora de publicacion de SUNAT es hora de Peru: corregir las ya guardadas como si fueran UTC

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-21

Hasta ahora "20/10/2026 20:44" (hora de Peru, como la muestra SUNAT) se
guardaba como 20:44 UTC, es decir 5 horas antes de la real: un mensaje
publicado a la 1 a.m. aparecia con la fecha del dia anterior.
"""
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE mensajes_buzon SET fecha_publicacion = fecha_publicacion + interval '5 hours' WHERE fecha_publicacion IS NOT NULL")


def downgrade() -> None:
    op.execute("UPDATE mensajes_buzon SET fecha_publicacion = fecha_publicacion - interval '5 hours' WHERE fecha_publicacion IS NOT NULL")
