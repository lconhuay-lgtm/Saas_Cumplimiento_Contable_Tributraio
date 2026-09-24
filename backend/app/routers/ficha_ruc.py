"""
Generar y servir el PDF de la "Ficha RUC" de una empresa (RUC, razon
social, estado del contribuyente, condicion de domicilio, actividad
economica -- la misma ficha que SUNAT muestra al hacer clic en "Ver Ficha
Ruc" dentro del Menu SOL).

Archivo separado de consultas.py a proposito: es una operacion distinta
(no lee el Buzon) con su propia cola/bitacora (FichaRucJob), aunque sigue
el mismo patron encolar -> pollear -> resultado que ya usan las consultas.
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Empresa, FichaRucJob, Usuario
from app.schemas import FichaRucJobResponse
from app.deps import get_usuario_actual
from app.queue_conn import cola_consultas
from app.jobs import ejecutar_generar_ficha_ruc
from app.rate_limit import verificar_limite_ruc, LimiteExcedido
from app.almacenamiento import leer_documento, AlmacenamientoError

router = APIRouter(tags=["ficha-ruc"])


def _get_empresa_del_tenant(empresa_id: str, usuario: Usuario, db: Session) -> Empresa:
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.tenant_id == usuario.tenant_id)
        .first()
    )
    if not empresa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa no encontrada")
    return empresa


@router.post("/empresas/{empresa_id}/ficha-ruc", response_model=FichaRucJobResponse, status_code=status.HTTP_202_ACCEPTED)
def generar_ficha_ruc(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = _get_empresa_del_tenant(empresa_id, usuario, db)

    try:
        verificar_limite_ruc(empresa.ruc)
    except LimiteExcedido as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    job = FichaRucJob(empresa_id=empresa.id, solicitado_por=usuario.id, estado="pendiente")
    db.add(job)
    db.commit()
    db.refresh(job)

    cola_consultas.enqueue(ejecutar_generar_ficha_ruc, job.id, job_timeout="10m")

    return job


@router.get("/empresas/{empresa_id}/ficha-ruc/jobs/{job_id}", response_model=FichaRucJobResponse)
def obtener_job_ficha_ruc(
    empresa_id: str,
    job_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = _get_empresa_del_tenant(empresa_id, usuario, db)
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
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = _get_empresa_del_tenant(empresa_id, usuario, db)
    if not empresa.ficha_ruc_pdf_ref:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todavia no se genero una Ficha RUC para esta empresa",
        )

    try:
        contenido = leer_documento(empresa.ficha_ruc_pdf_ref)
    except AlmacenamientoError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return Response(content=contenido, media_type="application/pdf")
