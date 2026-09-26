"""Agrega rol e imprime empresas asignadas a las invitaciones de usuario

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invitaciones_usuario",
        sa.Column("rol", sa.String(20), nullable=False, server_default="miembro"),
    )
    op.create_table(
        "invitaciones_usuario_empresas",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "invitacion_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("invitaciones_usuario.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.UniqueConstraint("invitacion_id", "empresa_id", name="uq_invitacion_empresa"),
    )
    op.create_index(
        "ix_invitaciones_usuario_empresas_invitacion_id",
        "invitaciones_usuario_empresas",
        ["invitacion_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_invitaciones_usuario_empresas_invitacion_id", table_name="invitaciones_usuario_empresas")
    op.drop_table("invitaciones_usuario_empresas")
    op.drop_column("invitaciones_usuario", "rol")
