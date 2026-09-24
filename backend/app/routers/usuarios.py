"""
Listado de usuarios del propio tenant -- hace falta para el selector de
"asignar a" en el detalle de cada empresa (ver Empresa.asignado_a_usuario_id
en models.py). No expone nada de otros tenants, mismo patron de aislamiento
que el resto de la API.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Usuario
from app.deps import get_usuario_actual
from app.schemas import UsuarioResponse

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


@router.get("", response_model=list[UsuarioResponse])
def listar_usuarios(
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    return (
        db.query(Usuario)
        .filter(Usuario.tenant_id == usuario.tenant_id)
        .order_by(Usuario.email.asc())
        .all()
    )
