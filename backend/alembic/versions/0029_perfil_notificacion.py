"""agrega preferencia de notificacion (correo/whatsapp) a usuarios

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usuarios",
        sa.Column("forma_notificacion", sa.String(length=20), nullable=False, server_default="correo"),
    )
    op.add_column("usuarios", sa.Column("celular", sa.String(length=20), nullable=True))
    op.add_column(
        "usuarios",
        sa.Column("pais_celular", sa.String(length=5), nullable=True, server_default="+51"),
    )
    op.alter_column("usuarios", "forma_notificacion", server_default=None)
    op.alter_column("usuarios", "pais_celular", server_default=None)


def downgrade() -> None:
    op.drop_column("usuarios", "pais_celular")
    op.drop_column("usuarios", "celular")
    op.drop_column("usuarios", "forma_notificacion")
