"""
SIRE (Sistema Integrado de Registros Electronicos): estado de presentacion del
Registro de Ventas e Ingresos (RVIE) y del Registro de Compras (RCE) por
periodo, leido de SUNAT SOL (Gestion de Ventas/Compras). Alimenta el modulo
Cumplimiento: una lectura trae todos los periodos de todos los anios de una
empresa, asi que el cuadro por anio se arma aca desde lo ya guardado.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ConsultaSireJob, CronogramaVencimiento, Empresa, SireEstadoPeriodo, Usuario
from app.cronograma_sunat import grupo_para_empresa
from app.cumplimiento import ESTADOS_EN_CURSO as _ESTADOS_EN_CURSO, encolar_lecturas, filtrar_activas_en_sunat
from app.schemas import (
    ConsultaSireJobResponse, CumplimientoSireFila, CumplimientoSireResponse,
    SireEstadoLibro, SirePeriodoItem,
)
from app.deps import get_usuario_actual
from app.queue_conn import cola_consultas
from app.jobs import ejecutar_consulta_sire
from app.rate_limit import verificar_limite_ruc, LimiteExcedido
from app.acceso import filtrar_empresas_visibles, obtener_empresa_visible

router = APIRouter(tags=["sire"])


@router.post("/empresas/{empresa_id}/sire/consultar", response_model=ConsultaSireJobResponse, status_code=status.HTTP_202_ACCEPTED)
def consultar_sire(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    en_curso = (
        db.query(ConsultaSireJob)
        .filter(ConsultaSireJob.empresa_id == empresa.id, ConsultaSireJob.estado.in_(_ESTADOS_EN_CURSO))
        .first()
    )
    if en_curso:
        return en_curso

    try:
        verificar_limite_ruc(empresa.ruc)
    except LimiteExcedido as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    job = ConsultaSireJob(empresa_id=empresa.id, solicitado_por=usuario.id, estado="pendiente")
    db.add(job)
    db.commit()
    db.refresh(job)
    cola_consultas.enqueue(ejecutar_consulta_sire, job.id, job_timeout="10m", at_front=True)
    return job


@router.get("/cumplimiento/sire", response_model=CumplimientoSireResponse)
def cumplimiento_sire(
    anio: int | None = None,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """Cuadro de control: estado SIRE (RVIE/RCE) de cada empresa visible, mes por mes, para un anio."""
    empresas = (
        filtrar_activas_en_sunat(filtrar_empresas_visibles(db.query(Empresa), usuario))
        .filter(Empresa.activo.is_(True))
        .order_by(Empresa.razon_social)
        .all()
    )
    ids = [e.id for e in empresas]

    anios = sorted(
        {int(p[:4]) for (p,) in db.query(SireEstadoPeriodo.periodo).filter(SireEstadoPeriodo.empresa_id.in_(ids)).distinct()},
        reverse=True,
    ) if ids else []
    anio_elegido = anio or (anios[0] if anios else datetime.now(timezone.utc).year)

    filas_estado = (
        db.query(SireEstadoPeriodo)
        .filter(SireEstadoPeriodo.empresa_id.in_(ids), SireEstadoPeriodo.periodo.like(f"{anio_elegido}-%"))
        .all()
    ) if ids else []
    vencimientos = {
        (periodo, grupo): fecha
        for periodo, grupo, fecha in db.query(
            CronogramaVencimiento.periodo_tributario, CronogramaVencimiento.grupo, CronogramaVencimiento.fecha_vencimiento
        ).filter(
            CronogramaVencimiento.tipo == "sire",
            CronogramaVencimiento.periodo_tributario.like(f"{anio_elegido}-%"),
        )
    }
    ultima_lectura = dict(
        db.query(SireEstadoPeriodo.empresa_id, func.max(SireEstadoPeriodo.actualizado_en))
        .filter(SireEstadoPeriodo.empresa_id.in_(ids))
        .group_by(SireEstadoPeriodo.empresa_id)
        .all()
    ) if ids else {}
    en_curso = {
        eid for (eid,) in db.query(ConsultaSireJob.empresa_id)
        .filter(ConsultaSireJob.empresa_id.in_(ids), ConsultaSireJob.estado.in_(_ESTADOS_EN_CURSO))
    } if ids else set()
    ultimo_job = {}
    for job in (
        db.query(ConsultaSireJob)
        .filter(ConsultaSireJob.empresa_id.in_(ids), ConsultaSireJob.estado.in_(("completado", "error")))
        .order_by(ConsultaSireJob.creado_en)
    ) if ids else []:
        ultimo_job[job.empresa_id] = job

    por_empresa: dict[str, dict[str, SirePeriodoItem]] = {}
    for f in filas_estado:
        item = por_empresa.setdefault(f.empresa_id, {}).setdefault(f.periodo, SirePeriodoItem(periodo=f.periodo))
        estado = SireEstadoLibro(cod_estado=f.cod_estado, des_estado=f.des_estado, presentado=f.presentado)
        if f.libro == "RVIE":
            item.rvie = estado
        elif f.libro == "RCE":
            item.rce = estado

    filas = []
    for e in empresas:
        grupo = grupo_para_empresa(e.ruc, e.es_buen_contribuyente)
        periodos = sorted(por_empresa.get(e.id, {}).values(), key=lambda i: i.periodo)
        for item in periodos:
            item.vence_el = vencimientos.get((item.periodo, grupo))
        job = ultimo_job.get(e.id)
        filas.append(CumplimientoSireFila(
            empresa_id=e.id,
            ruc=e.ruc,
            razon_social=e.razon_social,
            periodos=periodos,
            actualizado_en=ultima_lectura.get(e.id),
            consulta_en_curso=e.id in en_curso,
            ultimo_error=job.error if job is not None and job.estado == "error" else None,
        ))

    return CumplimientoSireResponse(anio=anio_elegido, anios_disponibles=anios, filas=filas)


@router.post("/cumplimiento/sire/consultar-todas")
def consultar_sire_todas(
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """Encola la lectura del SIRE de todas las empresas visibles, espaciadas igual que la consulta masiva del buzon."""
    empresas = (
        filtrar_activas_en_sunat(filtrar_empresas_visibles(db.query(Empresa), usuario))
        .filter(Empresa.activo.is_(True))
        .all()
    )
    return encolar_lecturas(db, empresas, ConsultaSireJob, ejecutar_consulta_sire, solicitado_por=usuario.id)
