"""agrega horario configurable de chequeo automatico a configuracion_sistema

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "configuracion_sistema",
        sa.Column("chequeo1_hora", sa.Integer(), nullable=False, server_default="16"),
    )
    op.add_column(
        "configuracion_sistema",
        sa.Column("chequeo1_minuto", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "configuracion_sistema",
        sa.Column("chequeo2_hora", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "configuracion_sistema",
        sa.Column("chequeo2_minuto", sa.Integer(), nullable=False, server_default="30"),
    )
    op.alter_column("configuracion_sistema", "chequeo1_hora", server_default=None)
    op.alter_column("configuracion_sistema", "chequeo1_minuto", server_default=None)
    op.alter_column("configuracion_sistema", "chequeo2_hora", server_default=None)
    op.alter_column("configuracion_sistema", "chequeo2_minuto", server_default=None)


def downgrade() -> None:
    op.drop_column("configuracion_sistema", "chequeo2_minuto")
    op.drop_column("configuracion_sistema", "chequeo2_hora")
    op.drop_column("configuracion_sistema", "chequeo1_minuto")
    op.drop_column("configuracion_sistema", "chequeo1_hora")
