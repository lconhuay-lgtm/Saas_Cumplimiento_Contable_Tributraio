"""PIN de 4 digitos por usuario para ver la clave SOL (PLAME) y registro de cada vista

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-05

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("pin_hash", sa.String(255), nullable=True))
    op.add_column("usuarios", sa.Column("pin_intentos_fallidos", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("usuarios", sa.Column("pin_bloqueado_hasta", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "vistas_clave_sol",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("usuario_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=False, index=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False, index=True),
        sa.Column("motivo", sa.String(20), nullable=False, server_default="plame"),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("vistas_clave_sol")
    op.drop_column("usuarios", "pin_bloqueado_hasta")
    op.drop_column("usuarios", "pin_intentos_fallidos")
    op.drop_column("usuarios", "pin_hash")
