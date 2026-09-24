"""agrega documento_ref a mensajes_buzon (visor de PDF)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mensajes_buzon",
        sa.Column("documento_ref", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mensajes_buzon", "documento_ref")
