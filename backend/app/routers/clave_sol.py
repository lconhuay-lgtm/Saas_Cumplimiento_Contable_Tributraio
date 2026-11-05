"""
Clave SOL para la PLAME.

La PLAME (PDT 601) se presenta en un programa de SUNAT que pide el RUC, el
usuario y la clave SOL a mano. Con un PIN de 4 digitos propio, cada usuario
ve esos datos de una empresa que ya puede ver (admin: todas; miembro: las
asignadas) y los copia.

- El PIN se crea o cambia con la contrasena de la cuenta: una sesion abierta
  olvidada no basta para crear un PIN y sacar claves.
- Tras PIN_INTENTOS_MAX PIN errados seguidos el PIN queda bloqueado
  PIN_MINUTOS_BLOQUEO minutos.
- Cada vista queda registrada en VistaClaveSol.
- Un PIN errado responde 400 (no 401): el tablero cierra la sesion ante un 401.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.acceso import obtener_empresa_visible
from app.database import get_db
from app.deps import get_usuario_actual
from app.models import CredencialSol, Usuario, VistaClaveSol
from app.schemas import ClaveSolResponse, EstadoPinResponse, GuardarPinRequest, VerClaveSolRequest
from app.security import descifrar_clave_sol, hash_password, verify_password

logger = logging.getLogger("app.routers.clave_sol")

router = APIRouter(tags=["clave_sol"])

PIN_INTENTOS_MAX = 5
PIN_MINUTOS_BLOQUEO = 15
# Cuanto tiempo muestra el tablero la clave antes de ocultarla sola.
SEGUNDOS_VISIBLE = 60


def _bloqueado_hasta(usuario: Usuario, ahora: datetime) -> datetime | None:
    hasta = usuario.pin_bloqueado_hasta
    if hasta and hasta.tzinfo is None:  # SQLite (pruebas) devuelve la fecha sin zona
        hasta = hasta.replace(tzinfo=timezone.utc)
    return hasta if hasta and hasta > ahora else None


@router.get("/auth/pin", response_model=EstadoPinResponse)
def estado_pin(usuario: Usuario = Depends(get_usuario_actual)):
    return EstadoPinResponse(tiene_pin=usuario.tiene_pin, bloqueado_hasta=_bloqueado_hasta(usuario, datetime.now(timezone.utc)))


@router.post("/auth/pin", response_model=EstadoPinResponse)
def guardar_pin(
    data: GuardarPinRequest,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """Crea el PIN o lo cambia (tambien si se olvido): siempre con la contrasena de la cuenta."""
    if not verify_password(data.password, usuario.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La contrasena de tu cuenta no es correcta.")
    usuario.pin_hash = hash_password(data.pin)
    usuario.pin_intentos_fallidos = 0
    usuario.pin_bloqueado_hasta = None
    db.commit()
    logger.info(f"PIN de clave SOL guardado por {usuario.email}")
    return EstadoPinResponse(tiene_pin=True)


@router.post("/empresas/{empresa_id}/clave-sol/ver", response_model=ClaveSolResponse)
def ver_clave_sol(
    empresa_id: str,
    data: VerClaveSolRequest,
    response: Response,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    if not usuario.pin_hash:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Primero crea tu PIN de 4 digitos.")
    ahora = datetime.now(timezone.utc)
    bloqueo = _bloqueado_hasta(usuario, ahora)
    if bloqueo:
        minutos = max(1, round((bloqueo - ahora).total_seconds() / 60))
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Tu PIN esta bloqueado por varios intentos errados. Intenta de nuevo en {minutos} minuto(s).",
        )

    if not verify_password(data.pin, usuario.pin_hash):
        usuario.pin_intentos_fallidos += 1
        restantes = PIN_INTENTOS_MAX - usuario.pin_intentos_fallidos
        if restantes <= 0:
            usuario.pin_intentos_fallidos = 0
            usuario.pin_bloqueado_hasta = ahora + timedelta(minutes=PIN_MINUTOS_BLOQUEO)
            db.commit()
            logger.warning(f"PIN de clave SOL bloqueado para {usuario.email}")
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"PIN incorrecto. Tu PIN queda bloqueado {PIN_MINUTOS_BLOQUEO} minutos.",
            )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PIN incorrecto. Te queda(n) {restantes} intento(s).",
        )

    usuario.pin_intentos_fallidos = 0
    credencial = db.query(CredencialSol).filter(CredencialSol.empresa_id == empresa.id).first()
    if not credencial:
        db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Esta empresa no tiene credenciales SOL guardadas.")
    clave = descifrar_clave_sol(credencial.clave_cifrada, credencial.dek_cifrada)
    db.add(VistaClaveSol(tenant_id=usuario.tenant_id, usuario_id=usuario.id, empresa_id=empresa.id, motivo="plame"))
    db.commit()
    logger.info(f"Clave SOL de {empresa.ruc} vista por {usuario.email} (PLAME)")
    response.headers["Cache-Control"] = "no-store"
    return ClaveSolResponse(
        ruc=empresa.ruc,
        razon_social=empresa.razon_social,
        usuario_sol=credencial.usuario_sol,
        clave_sol=clave,
        visible_seg=SEGUNDOS_VISIBLE,
    )
