"""MensajeBuzon: origen (notificaciones|mensajes) + contenido_texto para Buzon Mensajes

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mensajes_buzon",
        sa.Column("origen", sa.String(length=20), nullable=False, server_default="notificaciones"),
    )
    op.alter_column("mensajes_buzon", "origen", server_default=None)
    op.add_column("mensajes_buzon", sa.Column("contenido_texto", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("mensajes_buzon", "contenido_texto")
    op.drop_column("mensajes_buzon", "origen")
