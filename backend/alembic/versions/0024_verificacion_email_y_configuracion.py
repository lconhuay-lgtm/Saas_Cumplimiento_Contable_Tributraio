"""Fase 5: Usuario.email_verificado/token de activacion + tabla configuracion_sistema (panel maestro)

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default="true" para que los usuarios YA EXISTENTES queden
    # marcados como verificados de entrada (no deben aparecer de golpe con
    # un aviso de "verifica tu email" sin haber hecho nada distinto) --
    # se quita el default despues para que los usuarios NUEVOS (creados vía
    # ORM desde /auth/registro) respeten el default de Python (False).
    op.add_column(
        "usuarios",
        sa.Column("email_verificado", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.alter_column("usuarios", "email_verificado", server_default=None)
    op.add_column("usuarios", sa.Column("token_verificacion", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_usuarios_token_verificacion", "usuarios", ["token_verificacion"], unique=False
    )
    op.add_column(
        "usuarios", sa.Column("token_verificacion_expira", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "configuracion_sistema",
        sa.Column("id", sa.String(length=20), primary_key=True),
        sa.Column("limite_mensajes_por_consulta", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("espaciado_seg_entre_consultas", sa.Integer(), nullable=False, server_default="45"),
        sa.Column("concurrencia_maxima", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("segundos_entre_consultas_mismo_ruc", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "actualizado_por_usuario_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
    )
    # Fila unica -- mismos valores que ya regian por variable de entorno
    # (ver app/rate_limit.py), asi que crearla aca no cambia ningun
    # comportamiento hasta que alguien la edite desde el panel maestro.
    op.execute(
        "INSERT INTO configuracion_sistema (id, limite_mensajes_por_consulta, espaciado_seg_entre_consultas, "
        "concurrencia_maxima, segundos_entre_consultas_mismo_ruc, actualizado_en) "
        "VALUES ('global', 20, 45, 3, 60, now())"
    )


def downgrade() -> None:
    op.drop_table("configuracion_sistema")
    op.drop_column("usuarios", "token_verificacion_expira")
    op.drop_index("ix_usuarios_token_verificacion", table_name="usuarios")
    op.drop_column("usuarios", "token_verificacion")
    op.drop_column("usuarios", "email_verificado")
