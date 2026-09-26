"""
Invitar a un usuario adicional al MISMO tenant -- la puerta de entrada que
faltaba para un cliente con mas de un usuario (ej. un socio + un asistente):
antes de esto, la unica forma de sumar un segundo usuario al mismo tenant
era insertarlo directo en la base de datos. /auth/registro sigue existiendo
tal cual para el primer usuario de un tenant nuevo -- esto es solo para el
segundo en adelante.

Flujo: alguien ya logueado crea la invitacion (queda pendiente, con un
link de un solo uso) -> se manda un correo (o queda en modo prueba, ver
email_utils.py) -> quien lo recibe entra al link SIN estar logueado, pone
su contrasena, y queda como Usuario nuevo en el MISMO tenant.
"""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Usuario, Tenant, InvitacionUsuario, InvitacionUsuarioEmpresa, Empresa
from app.deps import get_admin_actual
from app.security import hash_password, crear_token
from app.email_utils import enviar_invitacion_equipo
from app.schemas import (
    InvitacionCreate,
    InvitacionResponse,
    InvitacionAceptarRequest,
    InvitacionInfoPublica,
    TokenResponse,
)

logger = logging.getLogger("app.routers.invitaciones")

router = APIRouter(prefix="/invitaciones", tags=["invitaciones"])

DIAS_VALIDEZ_INVITACION = 7
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")


def _link(token: str) -> str:
    return f"{FRONTEND_URL}/invitacion/{token}"


def _a_respuesta(inv: InvitacionUsuario, db: Session) -> InvitacionResponse:
    invitador = db.query(Usuario).filter(Usuario.id == inv.invitado_por_usuario_id).first()
    empresa_ids = [
        fila[0]
        for fila in db.query(InvitacionUsuarioEmpresa.empresa_id)
        .filter(InvitacionUsuarioEmpresa.invitacion_id == inv.id)
        .all()
    ]
    return InvitacionResponse(
        id=inv.id,
        email=inv.email,
        invitado_por_email=invitador.email if invitador else "?",
        rol=inv.rol,
        empresa_ids=empresa_ids,
        link=_link(inv.token),
        creado_en=inv.creado_en,
        expira_en=inv.expira_en,
        usado_en=inv.usado_en,
        cancelado_en=inv.cancelado_en,
    )


@router.get("", response_model=list[InvitacionResponse])
def listar_invitaciones(
    usuario: Usuario = Depends(get_admin_actual),
    db: Session = Depends(get_db),
):
    invitaciones = (
        db.query(InvitacionUsuario)
        .filter(InvitacionUsuario.tenant_id == usuario.tenant_id)
        .order_by(InvitacionUsuario.creado_en.desc())
        .all()
    )
    return [_a_respuesta(inv, db) for inv in invitaciones]


@router.post("", response_model=InvitacionResponse, status_code=status.HTTP_201_CREATED)
def crear_invitacion(
    data: InvitacionCreate,
    usuario: Usuario = Depends(get_admin_actual),
    db: Session = Depends(get_db),
):
    email_normalizado = data.email.strip().lower()

    if data.rol not in ("admin", "miembro"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rol invalido -- debe ser 'admin' o 'miembro'")

    # Las empresas elegidas solo tienen sentido para "miembro" -- un admin
    # ve todas las del tenant igual (ver acceso.py), asi que si llegan
    # empresa_ids con rol="admin" se ignoran en silencio en vez de fallar.
    empresa_ids_validos: list[str] = []
    if data.rol == "miembro" and data.empresa_ids:
        empresa_ids_validos = [
            fila[0]
            for fila in db.query(Empresa.id)
            .filter(Empresa.id.in_(data.empresa_ids), Empresa.tenant_id == usuario.tenant_id)
            .all()
        ]
        if len(empresa_ids_validos) != len(set(data.empresa_ids)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Una o mas empresas no existen o no pertenecen a este tenant",
            )

    ya_es_usuario = db.query(Usuario).filter(Usuario.email == email_normalizado).first()
    if ya_es_usuario:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese email ya tiene una cuenta")

    ahora = datetime.now(timezone.utc)
    pendiente = (
        db.query(InvitacionUsuario)
        .filter(
            InvitacionUsuario.tenant_id == usuario.tenant_id,
            InvitacionUsuario.email == email_normalizado,
            InvitacionUsuario.usado_en.is_(None),
            InvitacionUsuario.cancelado_en.is_(None),
            InvitacionUsuario.expira_en > ahora,
        )
        .first()
    )
    if pendiente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay una invitacion pendiente para ese email -- cancelala primero si queres mandar una nueva",
        )

    tenant = db.query(Tenant).filter(Tenant.id == usuario.tenant_id).first()

    invitacion = InvitacionUsuario(
        tenant_id=usuario.tenant_id,
        email=email_normalizado,
        token=secrets.token_urlsafe(32),
        invitado_por_usuario_id=usuario.id,
        rol=data.rol,
        expira_en=ahora + timedelta(days=DIAS_VALIDEZ_INVITACION),
    )
    db.add(invitacion)
    db.flush()
    for empresa_id in empresa_ids_validos:
        db.add(InvitacionUsuarioEmpresa(invitacion_id=invitacion.id, empresa_id=empresa_id))
    db.commit()
    db.refresh(invitacion)

    # Un fallo mandando el correo NUNCA debe perder la invitacion ya creada
    # -- el link sigue siendo valido y viaja en la respuesta (ver
    # InvitacionResponse.link), asi el admin lo puede copiar a mano si el
    # correo no llega (o esta en modo prueba, ver email_utils.py).
    try:
        enviar_invitacion_equipo(email_normalizado, tenant.nombre, usuario.email, _link(invitacion.token))
    except Exception as e:
        logger.warning(f"No se pudo enviar el correo de invitacion a {email_normalizado}: {e}")

    return _a_respuesta(invitacion, db)


@router.delete("/{invitacion_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancelar_invitacion(
    invitacion_id: str,
    usuario: Usuario = Depends(get_admin_actual),
    db: Session = Depends(get_db),
):
    invitacion = (
        db.query(InvitacionUsuario)
        .filter(InvitacionUsuario.id == invitacion_id, InvitacionUsuario.tenant_id == usuario.tenant_id)
        .first()
    )
    if not invitacion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitacion no encontrada")
    invitacion.cancelado_en = datetime.now(timezone.utc)
    db.commit()


# ---- Endpoints publicos (sin auth) -- para quien recibe la invitacion, que todavia no tiene cuenta ----


def _con_utc(momento):
    # Mismo ajuste que en admin.py/dashboard.py/cronograma_sunat.py: SQLite
    # (pruebas) devuelve datetimes "naive" aunque la columna sea
    # DateTime(timezone=True); Postgres (produccion) los devuelve con
    # tzinfo. Sin esto, comparar un naive con uno aware revienta con
    # TypeError.
    if momento is not None and momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


def _validar_token(token: str, db: Session) -> tuple[InvitacionUsuario | None, str | None]:
    invitacion = db.query(InvitacionUsuario).filter(InvitacionUsuario.token == token).first()
    if not invitacion:
        return None, "Este link de invitacion no es valido."
    if invitacion.cancelado_en is not None:
        return None, "Esta invitacion fue cancelada."
    if invitacion.usado_en is not None:
        return None, "Esta invitacion ya fue usada."
    if _con_utc(invitacion.expira_en) < datetime.now(timezone.utc):
        return None, "Esta invitacion ya vencio -- pedile a quien te invito que te mande una nueva."
    return invitacion, None


@router.get("/{token}/info", response_model=InvitacionInfoPublica)
def info_invitacion(token: str, db: Session = Depends(get_db)):
    """Lo que ve la pantalla publica ANTES de aceptar, para mostrar 'te invitaron a X' sin exponer nada mas del tenant."""
    invitacion, motivo_invalido = _validar_token(token, db)
    if invitacion is None:
        return InvitacionInfoPublica(valido=False, motivo_invalido=motivo_invalido)
    tenant = db.query(Tenant).filter(Tenant.id == invitacion.tenant_id).first()
    return InvitacionInfoPublica(valido=True, tenant_nombre=tenant.nombre if tenant else "?", email=invitacion.email)


@router.post("/{token}/aceptar", response_model=TokenResponse)
def aceptar_invitacion(token: str, data: InvitacionAceptarRequest, db: Session = Depends(get_db)):
    invitacion, motivo_invalido = _validar_token(token, db)
    if invitacion is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=motivo_invalido)

    ya_es_usuario = db.query(Usuario).filter(Usuario.email == invitacion.email).first()
    if ya_es_usuario:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese email ya tiene una cuenta")

    # El rol lo elige el admin al crear la invitacion (ver crear_invitacion
    # arriba) -- "miembro" ve solo las empresas asignadas (mas abajo) y no
    # puede reasignar carteras ni entrar a Salud del sistema / Mi equipo
    # (ver app/acceso.py y app/deps.py:get_admin_actual).
    nuevo_usuario = Usuario(
        tenant_id=invitacion.tenant_id,
        email=invitacion.email,
        password_hash=hash_password(data.password),
        rol=invitacion.rol,
    )
    db.add(nuevo_usuario)
    db.flush()

    if invitacion.rol == "miembro":
        empresa_ids = [
            fila[0]
            for fila in db.query(InvitacionUsuarioEmpresa.empresa_id)
            .filter(InvitacionUsuarioEmpresa.invitacion_id == invitacion.id)
            .all()
        ]
        if empresa_ids:
            db.query(Empresa).filter(Empresa.id.in_(empresa_ids)).update(
                {Empresa.asignado_a_usuario_id: nuevo_usuario.id}, synchronize_session=False
            )

    invitacion.usado_en = datetime.now(timezone.utc)
    db.commit()
    db.refresh(nuevo_usuario)

    token_acceso = crear_token(usuario_id=nuevo_usuario.id, tenant_id=nuevo_usuario.tenant_id)
    return TokenResponse(access_token=token_acceso)
