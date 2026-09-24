"""
Generar y servir el PDF de la "Ficha RUC" de una empresa (RUC, razon
social, estado del contribuyente, condicion de domicilio, actividad
economica -- la misma ficha que SUNAT muestra al hacer clic en "Ver Ficha
Ruc" dentro del Menu SOL).

Archivo separado de consultas.py a proposito: es una operacion distinta
(no lee el Buzon) con su propia cola/bitacora (FichaRucJob), aunque sigue
el mismo patron encolar -> pollear -> resultado que ya usan las consultas.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Empresa, FichaRucJob, Usuario
from app.schemas import FichaRucJobResponse, LimiteDiarioResponse
from app.deps import get_usuario_actual
from app.queue_conn import cola_consultas
from app.jobs import ejecutar_generar_ficha_ruc
from app.rate_limit import verificar_limite_ruc, LimiteExcedido
from app.almacenamiento import leer_documento, AlmacenamientoError
from app.acceso import obtener_empresa_visible

router = APIRouter(tags=["ficha-ruc"])

# SUNAT permite generar como maximo 3 "Reporte de Ficha RUC" (con QR) por
# dia POR EMPRESA -- a partir del 4to, devuelve en silencio el ultimo ya
# generado (nunca un error). Se expone via /limite-qr para que el
# frontend avise ANTES de que el usuario choque con ese limite silencioso.
LIMITE_REPORTES_QR_POR_DIA = 3


@router.post("/empresas/{empresa_id}/ficha-ruc", response_model=FichaRucJobResponse, status_code=status.HTTP_202_ACCEPTED)
def generar_ficha_ruc(
    empresa_id: str,
    con_qr: bool = False,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)

    try:
        verificar_limite_ruc(empresa.ruc)
    except LimiteExcedido as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    job = FichaRucJob(empresa_id=empresa.id, solicitado_por=usuario.id, estado="pendiente", con_qr=con_qr)
    db.add(job)
    db.commit()
    db.refresh(job)

    cola_consultas.enqueue(ejecutar_generar_ficha_ruc, job.id, job_timeout="10m")

    return job


@router.get("/empresas/{empresa_id}/ficha-ruc/limite-qr", response_model=LimiteDiarioResponse)
def limite_qr_ficha_ruc(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """Cuantos "Reporte de Ficha RUC" con QR se generaron HOY para esta empresa -- ver LIMITE_REPORTES_QR_POR_DIA."""
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    inicio_de_hoy = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    usados_hoy = (
        db.query(FichaRucJob)
        .filter(
            FichaRucJob.empresa_id == empresa.id,
            FichaRucJob.con_qr.is_(True),
            FichaRucJob.estado == "completado",
            FichaRucJob.creado_en >= inicio_de_hoy,
        )
        .count()
    )
    return LimiteDiarioResponse(usados_hoy=usados_hoy, limite=LIMITE_REPORTES_QR_POR_DIA)


@router.get("/empresas/{empresa_id}/ficha-ruc/jobs/{job_id}", response_model=FichaRucJobResponse)
def obtener_job_ficha_ruc(
    empresa_id: str,
    job_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    job = (
        db.query(FichaRucJob)
        .filter(FichaRucJob.id == job_id, FichaRucJob.empresa_id == empresa.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job no encontrado")
    return job


@router.get("/empresas/{empresa_id}/ficha-ruc/pdf")
def obtener_pdf_ficha_ruc(
    empresa_id: str,
    con_qr: bool = False,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    referencia = empresa.ficha_ruc_qr_pdf_ref if con_qr else empresa.ficha_ruc_pdf_ref
    if not referencia:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todavia no se genero una Ficha RUC para esta empresa",
        )

    try:
        contenido = leer_documento(referencia)
    except AlmacenamientoError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return Response(content=contenido, media_type="application/pdf")
