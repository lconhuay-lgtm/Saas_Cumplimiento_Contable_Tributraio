"""
Modulo de cronograma SUNAT: endpoints para sincronizar el cronograma oficial
de vencimientos, ver la agenda por mes, y los proximos vencimientos (usado
por el aviso del Dashboard). Ver app.cronograma_sunat para toda la logica
de descarga/parseo/matching -- este router solo la expone como API.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Usuario
from app.deps import get_usuario_actual
from app.schemas import (
    CronogramaSincronizarResponse,
    AgendaMesResponse,
    VencimientoAgendaItem,
    ProximoVencimientoItem,
)
from app import cronograma_sunat

router = APIRouter(prefix="/cronograma", tags=["cronograma"])


@router.post("/sincronizar", response_model=CronogramaSincronizarResponse)
def sincronizar(
    anio: int | None = None,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Descarga y guarda (a mano, sin esperar al chequeo automatico diario) el
    cronograma oficial de SUNAT de un ejercicio -- pensado para el boton
    "Sincronizar" del modulo Cronograma, por si SUNAT publica una
    modificacion (p.ej. una prorroga) a mitad de ano y no se quiere esperar
    hasta el proximo chequeo automatico.
    """
    anio_objetivo = anio or datetime.now(timezone.utc).year
    try:
        resultado = cronograma_sunat.sincronizar_cronograma(db, anio_objetivo)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo sincronizar el cronograma {anio_objetivo}: {e}",
        )
    return CronogramaSincronizarResponse(**resultado)


@router.get("/agenda", response_model=AgendaMesResponse)
def agenda_mes(
    anio: int,
    mes: int,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """Vencimientos del mes/anio pedido, para las empresas activas del tenant -- vista de calendario."""
    if not (1 <= mes <= 12):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="mes debe estar entre 1 y 12")
    vencimientos = cronograma_sunat.agenda_mes_por_tenant(db, usuario.tenant_id, anio, mes, usuario)
    return AgendaMesResponse(
        anio=anio,
        mes=mes,
        vencimientos=[VencimientoAgendaItem(**v) for v in vencimientos],
    )


@router.get("/proximos", response_model=list[ProximoVencimientoItem])
def proximos_vencimientos(
    dias_adelante: int = 15,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """El proximo vencimiento de cada empresa activa del tenant, si cae dentro de `dias_adelante` dias -- usado por el aviso del Dashboard."""
    resultado = cronograma_sunat.proximos_vencimientos_por_tenant(db, usuario.tenant_id, dias_adelante, usuario)
    return [ProximoVencimientoItem(**v) for v in resultado]
