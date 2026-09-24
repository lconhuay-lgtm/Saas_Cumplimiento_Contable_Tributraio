"""Invitaciones para sumar usuarios adicionales al mismo tenant

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invitaciones_usuario",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("invitado_por_usuario_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelado_en", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_invitaciones_usuario_tenant_id", "invitaciones_usuario", ["tenant_id"])
    op.create_index("ix_invitaciones_usuario_email", "invitaciones_usuario", ["email"])
    op.create_index("ix_invitaciones_usuario_token", "invitaciones_usuario", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_invitaciones_usuario_token", table_name="invitaciones_usuario")
    op.drop_index("ix_invitaciones_usuario_email", table_name="invitaciones_usuario")
    op.drop_index("ix_invitaciones_usuario_tenant_id", table_name="invitaciones_usuario")
    op.drop_table("invitaciones_usuario")
