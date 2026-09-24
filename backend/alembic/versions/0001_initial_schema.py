"""esquema inicial -- tenants, usuarios, empresas, credenciales_sol, mensajes_buzon, consultas_jobs

Revision ID: 0001
Revises:
Create Date: 2026-09-06

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "usuarios",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("rol", sa.String(20), nullable=False, server_default="admin"),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ultimo_login", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_usuarios_email", "usuarios", ["email"], unique=True)

    op.create_table(
        "empresas",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("ruc", sa.String(11), nullable=False),
        sa.Column("razon_social", sa.String(255), nullable=False),
        sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ultima_consulta_en", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "ruc", name="uq_empresa_tenant_ruc"),
    )
    op.create_index("ix_empresas_tenant_id", "empresas", ["tenant_id"])
    op.create_index("ix_empresas_ruc", "empresas", ["ruc"])

    op.create_table(
        "credenciales_sol",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False, unique=True),
        sa.Column("usuario_sol", sa.String(100), nullable=False),
        sa.Column("clave_cifrada", sa.LargeBinary, nullable=False),
        sa.Column("dek_cifrada", sa.LargeBinary, nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "mensajes_buzon",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("mensaje_externo_id", sa.String(500), nullable=False),
        sa.Column("fecha_publicacion", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asunto", sa.String(500), nullable=False),
        sa.Column("tipo", sa.String(100), nullable=True),
        sa.Column("leido", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("descubierto_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("empresa_id", "mensaje_externo_id", name="uq_mensaje_empresa_externo"),
    )
    op.create_index("ix_mensajes_buzon_empresa_id", "mensajes_buzon", ["empresa_id"])

    op.create_table(
        "consultas_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("empresa_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("solicitado_por", postgresql.UUID(as_uuid=False), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("iniciado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mensajes_nuevos", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.String(1000), nullable=True),
    )
    op.create_index("ix_consultas_jobs_empresa_id", "consultas_jobs", ["empresa_id"])
    op.create_index("ix_consultas_jobs_estado", "consultas_jobs", ["estado"])


def downgrade() -> None:
    op.drop_table("consultas_jobs")
    op.drop_table("mensajes_buzon")
    op.drop_table("credenciales_sol")
    op.drop_table("empresas")
    op.drop_table("usuarios")
    op.drop_table("tenants")
