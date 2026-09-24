"""Reporte de Ficha RUC con codigo QR (documento separado del CIR normal)

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("empresas", sa.Column("ficha_ruc_qr_pdf_ref", sa.String(500), nullable=True))
    op.add_column("empresas", sa.Column("ficha_ruc_qr_generada_en", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ficha_ruc_jobs",
        sa.Column("con_qr", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("ficha_ruc_jobs", "con_qr")
    op.drop_column("empresas", "ficha_ruc_qr_generada_en")
    op.drop_column("empresas", "ficha_ruc_qr_pdf_ref")
