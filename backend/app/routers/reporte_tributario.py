"""
Solicitar el "Reporte Tributario para Terceros" de una empresa (informacion
RESERVADA segun el Art. 85 del Codigo Tributario -- Dec. Sup. N 133-2013-EF
-- a diferencia de la Ficha RUC, que es publica). SUNAT lo genera y lo
manda por su cuenta al correo indicado -- este sistema no descarga ni
guarda ningun PDF, solo dispara la solicitud y confirma el envio.

Archivo separado de ficha_ruc.py: aunque el patron encolar -> pollear es
el mismo, es una operacion legalmente distinta (requiere aceptar un aviso
de informacion reservada cada vez) con su propia cola/bitacora
(ReporteTributarioJob).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ReporteTributarioJob, Usuario
from app.schemas import ReporteTributarioCreate, ReporteTributarioJobResponse, LimiteDiarioResponse
from app.deps import get_usuario_actual
from app.queue_conn import cola_consultas
from app.jobs import ejecutar_generar_reporte_tributario
from app.rate_limit import verificar_limite_ruc, LimiteExcedido
from app.acceso import obtener_empresa_visible

router = APIRouter(tags=["reporte-tributario"])

# SUNAT permite generar como maximo 3 "Reporte Tributario para Terceros"
# por dia POR EMPRESA -- a partir del 4to, reenvia el ultimo ya generado
# sin avisar. Mismo limite (y mismo motivo de exponerlo) que
# LIMITE_REPORTES_QR_POR_DIA en ficha_ruc.py.
LIMITE_REPORTES_POR_DIA = 3


@router.post("/empresas/{empresa_id}/reporte-tributario", response_model=ReporteTributarioJobResponse, status_code=status.HTTP_202_ACCEPTED)
def generar_reporte_tributario(
    empresa_id: str,
    data: ReporteTributarioCreate,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)

    try:
        verificar_limite_ruc(empresa.ruc)
    except LimiteExcedido as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    job = ReporteTributarioJob(
        empresa_id=empresa.id,
        solicitado_por=usuario.id,
        estado="pendiente",
        correo_destino=data.correo_destino,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    cola_consultas.enqueue(ejecutar_generar_reporte_tributario, job.id, job_timeout="10m")

    return job


@router.get("/empresas/{empresa_id}/reporte-tributario/jobs/{job_id}", response_model=ReporteTributarioJobResponse)
def obtener_job_reporte_tributario(
    empresa_id: str,
    job_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    job = (
        db.query(ReporteTributarioJob)
        .filter(ReporteTributarioJob.id == job_id, ReporteTributarioJob.empresa_id == empresa.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job no encontrado")
    return job


@router.get("/empresas/{empresa_id}/reporte-tributario/limite", response_model=LimiteDiarioResponse)
def limite_reporte_tributario(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """Cuantos "Reporte Tributario para Terceros" se solicitaron HOY para esta empresa -- ver LIMITE_REPORTES_POR_DIA."""
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    inicio_de_hoy = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    usados_hoy = (
        db.query(ReporteTributarioJob)
        .filter(
            ReporteTributarioJob.empresa_id == empresa.id,
            ReporteTributarioJob.estado == "completado",
            ReporteTributarioJob.creado_en >= inicio_de_hoy,
        )
        .count()
    )
    return LimiteDiarioResponse(usados_hoy=usados_hoy, limite=LIMITE_REPORTES_POR_DIA)
