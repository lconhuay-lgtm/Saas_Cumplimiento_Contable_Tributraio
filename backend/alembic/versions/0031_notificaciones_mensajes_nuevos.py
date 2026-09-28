"""notificaciones de mensajes nuevos: ConsultaJob.es_alta_inicial + MensajeBuzon.notificado_popup

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-27

"""
from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # False para TODOS (existentes y nuevos) -- solo importa distinguir la
    # consulta del alta inicial de una empresa (ver empresas.py) de
    # cualquier otra, y las empresas ya existentes no tienen ese concepto
    # retroactivamente.
    op.add_column(
        "consultas_jobs",
        sa.Column("es_alta_inicial", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.alter_column("consultas_jobs", "es_alta_inicial", server_default=None)

    # server_default="true" para que los mensajes YA EXISTENTES no
    # disparen de golpe la ventana emergente de "mensajes nuevos" para
    # todos los tenants apenas se despliegue esto -- mismo criterio que
    # email_verificado en la migracion 0024. Se quita el default despues
    # para que los mensajes NUEVOS (insertados via ORM desde jobs.py)
    # respeten lo que decida esa corrida (ver jobs.py: notificado_popup =
    # job.es_alta_inicial).
    op.add_column(
        "mensajes_buzon",
        sa.Column("notificado_popup", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.alter_column("mensajes_buzon", "notificado_popup", server_default=None)


def downgrade() -> None:
    op.drop_column("mensajes_buzon", "notificado_popup")
    op.drop_column("consultas_jobs", "es_alta_inicial")
