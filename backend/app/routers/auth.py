"""Registro de tenant + usuario admin, login, y verificacion de email (Fase 5)."""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant, Usuario
from app.schemas import (
    RegistroRequest,
    LoginRequest,
    TokenResponse,
    UsuarioResponse,
    VerificacionEmailResponse,
    ReenviarVerificacionResponse,
    ActualizarPerfilRequest,
    CambiarPasswordRequest,
    CambiarPasswordResponse,
)
from app.security import hash_password, verify_password, crear_token
from app.deps import get_usuario_actual
from app.email_utils import enviar_verificacion_email

logger = logging.getLogger("app.routers.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

DIAS_VALIDEZ_VERIFICACION = 3
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")


def _link_verificacion(token: str) -> str:
    return f"{FRONTEND_URL}/verificar-email/{token}"


def _generar_y_enviar_verificacion(usuario: Usuario, db: Session) -> None:
    """
    Regenera el token de verificacion y manda el correo -- usado tanto en
    /auth/registro como en /auth/reenviar-verificacion. Un fallo mandando
    el correo NUNCA debe perder al usuario ya creado ni tumbar el registro
    (mismo criterio que enviar_invitacion_equipo en routers/invitaciones.py)
    -- se deja en el log, el usuario puede pedir un reenvio despues.
    """
    usuario.token_verificacion = secrets.token_urlsafe(32)
    usuario.token_verificacion_expira = datetime.now(timezone.utc) + timedelta(days=DIAS_VALIDEZ_VERIFICACION)
    db.commit()
    try:
        enviar_verificacion_email(usuario.email, _link_verificacion(usuario.token_verificacion))
    except Exception as e:
        logger.warning(f"No se pudo enviar el correo de verificacion a {usuario.email}: {e}")


@router.post("/registro", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def registro(data: RegistroRequest, db: Session = Depends(get_db)):
    """Crea un tenant nuevo (estudio contable) con su primer usuario admin."""
    existente = db.query(Usuario).filter(Usuario.email == data.email).first()
    if existente:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese email ya esta registrado")

    tenant = Tenant(nombre=data.nombre_tenant)
    db.add(tenant)
    db.flush()  # asigna tenant.id sin cerrar la transaccion

    usuario = Usuario(
        tenant_id=tenant.id,
        email=data.email,
        password_hash=hash_password(data.password),
        rol="admin",
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)

    _generar_y_enviar_verificacion(usuario, db)

    token = crear_token(usuario_id=usuario.id, tenant_id=tenant.id)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.email == data.email).first()
    if not usuario or not verify_password(data.password, usuario.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email o contrasena incorrectos")

    token = crear_token(usuario_id=usuario.id, tenant_id=usuario.tenant_id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UsuarioResponse)
def me(usuario: Usuario = Depends(get_usuario_actual)):
    return usuario


@router.put("/perfil", response_model=UsuarioResponse)
def actualizar_perfil(
    data: ActualizarPerfilRequest,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Punto 2 (menu de cuenta): actualizacion PARCIAL (exclude_unset, mismo
    patron que /admin/configuracion) -- la pestana Perfil manda solo
    nombre/apellidos/celular/pais_celular, y la pestana Notificaciones manda
    solo forma_notificacion, sin pisarse una a la otra.
    """
    cambios = data.model_dump(exclude_unset=True)
    for campo, valor in cambios.items():
        setattr(usuario, campo, valor)
    db.commit()
    db.refresh(usuario)
    return usuario


@router.post("/cambiar-password", response_model=CambiarPasswordResponse)
def cambiar_password(
    data: CambiarPasswordRequest,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """Punto 2 (menu de cuenta): exige la contrasena actual -- evita que una sesion abierta olvidada sirva para tomar la cuenta."""
    if not verify_password(data.password_actual, usuario.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La contrasena actual no es correcta")
    usuario.password_hash = hash_password(data.password_nuevo)
    db.commit()
    return CambiarPasswordResponse(actualizado=True)


@router.post("/reenviar-verificacion", response_model=ReenviarVerificacionResponse)
def reenviar_verificacion(usuario: Usuario = Depends(get_usuario_actual), db: Session = Depends(get_db)):
    if usuario.email_verificado:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tu correo ya esta verificado.")
    _generar_y_enviar_verificacion(usuario, db)
    return ReenviarVerificacionResponse(enviado=True)


@router.post("/verificar-email/{token}", response_model=VerificacionEmailResponse)
def verificar_email(token: str, db: Session = Depends(get_db)):
    """Publico (sin auth) -- quien hace clic en el link del correo puede no tener sesion abierta en ese navegador."""
    usuario = db.query(Usuario).filter(Usuario.token_verificacion == token).first()
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este link de verificacion no es valido.")

    expira = usuario.token_verificacion_expira
    if expira is not None and expira.tzinfo is None:
        expira = expira.replace(tzinfo=timezone.utc)
    if expira is None or expira < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este link de verificacion vencio -- pide uno nuevo desde el tablero.",
        )

    usuario.email_verificado = True
    usuario.token_verificacion = None
    usuario.token_verificacion_expira = None
    db.commit()

    return VerificacionEmailResponse(verificado=True, mensaje="Tu correo quedo verificado.")
