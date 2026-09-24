"""Dependencias compartidas de FastAPI (usuario autenticado actual)."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Usuario
from app.security import decodificar_token

bearer_scheme = HTTPBearer()


def get_usuario_actual(
    credenciales: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    payload = decodificar_token(credenciales.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido o expirado")

    usuario = db.query(Usuario).filter(Usuario.id == payload.get("sub")).first()
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")
    return usuario


def get_staff_actual(usuario: Usuario = Depends(get_usuario_actual)) -> Usuario:
    """
    Igual que get_usuario_actual, pero ademas exige es_staff_plataforma=True.
    Usar en endpoints operativos que afectan a TODOS los tenants a la vez
    (chequeo nocturno, resumenes, canario, reclasificacion masiva) -- nunca
    en endpoints que un cliente deba poder llamar sobre sus propios datos
    (fix Fase R2, ver backend/app/routers/admin.py).
    """
    if not usuario.es_staff_plataforma:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este endpoint es solo para el equipo operador de la plataforma.",
        )
    return usuario


def get_admin_actual(usuario: Usuario = Depends(get_usuario_actual)) -> Usuario:
    """
    Igual que get_usuario_actual, pero ademas exige rol="admin" DENTRO del
    propio tenant -- a diferencia de get_staff_actual (que es sobre TODOS
    los tenants, para el equipo que opera la plataforma), esto es sobre UN
    tenant: el socio/admin de un estudio contable vs. un asistente
    ("miembro") con una cartera de empresas asignada. Usar en endpoints que
    no deberian ser visibles para un miembro (Salud del sistema, invitar
    companeros de equipo).
    """
    if usuario.rol != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este endpoint es solo para el administrador de la cuenta.",
        )
    return usuario
