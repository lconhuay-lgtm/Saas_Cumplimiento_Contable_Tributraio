"""
Declaracion mensual: formularios presentados ante SUNAT por periodo (Menu
SOL > Consulto mis declaraciones y pagos > Consulta general), para la
pestana "Declaracion mensual" del modulo Cumplimiento. El cuadro controla el
0621 (IGV-Renta mensual) y el 0601 (PLAME); el resto (boletas de pago, etc.)
se muestra en el detalle de cada periodo.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    ConsultaDeclaracionesJob, CronogramaVencimiento, DeclaracionSunat, Empresa, EmpresaObligacion, Usuario,
)
from app.cronograma_sunat import grupo_para_empresa
from app.cumplimiento import ESTADOS_EN_CURSO, encolar_lecturas, filtrar_activas_en_sunat
from app.schemas import (
    ConsultaDeclaracionesJobResponse, ControlFormularioRequest, CumplimientoDeclaracionesFila,
    CumplimientoDeclaracionesResponse, DeclaracionItem, DeclaracionPeriodoItem,
)
from app.deps import get_usuario_actual
from app.queue_conn import cola_consultas
from app.jobs import ejecutar_consulta_declaraciones
from app.rate_limit import verificar_limite_ruc, LimiteExcedido
from app.acceso import filtrar_empresas_visibles, obtener_empresa_visible
from app.tareas import cambiar_control_formulario

router = APIRouter(tags=["declaraciones"])

# Formularios que controla el cuadro -> tipo de EmpresaObligacion que los exige.
FORMULARIOS_CONTROLADOS = {"0621": "igv_renta", "0601": "planilla"}
SIEMPRE = "0000-00"
_ZONA_LIMA = timezone(timedelta(hours=-5))


def _ultimo_periodo_consultable() -> str:
    hoy = datetime.now(_ZONA_LIMA)
    anio, mes = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    return f"{anio}-{mes:02d}"


def _empresas_cumplimiento(db: Session, usuario: Usuario):
    return (
        filtrar_activas_en_sunat(filtrar_empresas_visibles(db.query(Empresa), usuario))
        .filter(Empresa.activo.is_(True))
        .order_by(Empresa.razon_social)
        .all()
    )


@router.post(
    "/empresas/{empresa_id}/declaraciones/consultar",
    response_model=ConsultaDeclaracionesJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def consultar_declaraciones(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    en_curso = (
        db.query(ConsultaDeclaracionesJob)
        .filter(ConsultaDeclaracionesJob.empresa_id == empresa.id, ConsultaDeclaracionesJob.estado.in_(ESTADOS_EN_CURSO))
        .first()
    )
    if en_curso:
        return en_curso
    try:
        verificar_limite_ruc(empresa.ruc)
    except LimiteExcedido as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    job = ConsultaDeclaracionesJob(empresa_id=empresa.id, solicitado_por=usuario.id, estado="pendiente")
    db.add(job)
    db.commit()
    db.refresh(job)
    cola_consultas.enqueue(ejecutar_consulta_declaraciones, job.id, job_timeout="10m", at_front=True)
    return job


@router.get("/cumplimiento/declaraciones", response_model=CumplimientoDeclaracionesResponse)
def cumplimiento_declaraciones(
    anio: int | None = None,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """Cuadro de control: formularios presentados por cada empresa visible, mes por mes, para un anio."""
    ultimo = _ultimo_periodo_consultable()
    empresas = _empresas_cumplimiento(db, usuario)
    ids = [e.id for e in empresas]
    if not ids:
        anio_vacio = anio or int(ultimo[:4])
        return CumplimientoDeclaracionesResponse(anio=anio_vacio, anios_disponibles=[], ultimo_periodo_consultable=ultimo, filas=[])

    anios = sorted(
        {int(p[:4]) for (p,) in db.query(DeclaracionSunat.periodo).filter(DeclaracionSunat.empresa_id.in_(ids)).distinct()},
        reverse=True,
    )
    anio_elegido = anio or (anios[0] if anios else int(ultimo[:4]))

    por_empresa: dict[str, dict[str, list[DeclaracionSunat]]] = {}
    for d in (
        db.query(DeclaracionSunat)
        .filter(DeclaracionSunat.empresa_id.in_(ids), DeclaracionSunat.periodo.like(f"{anio_elegido}-%"))
        .order_by(DeclaracionSunat.periodo, DeclaracionSunat.fecha_presentacion, DeclaracionSunat.formulario)
    ):
        por_empresa.setdefault(d.empresa_id, {}).setdefault(d.periodo, []).append(d)

    primer_periodo = {
        (eid, form): periodo
        for eid, form, periodo in db.query(
            DeclaracionSunat.empresa_id, DeclaracionSunat.formulario, func.min(DeclaracionSunat.periodo)
        )
        .filter(DeclaracionSunat.empresa_id.in_(ids), DeclaracionSunat.formulario.in_(list(FORMULARIOS_CONTROLADOS)))
        .group_by(DeclaracionSunat.empresa_id, DeclaracionSunat.formulario)
    }
    # Solo obligaciones que siguen el cronograma de SUNAT: una "Planilla
    # mensual" con dia fijo es el pago de sueldos, no la obligacion de PLAME.
    obligaciones = set()
    apagadas = set()
    for eid, tipo, activa in db.query(EmpresaObligacion.empresa_id, EmpresaObligacion.tipo, EmpresaObligacion.activa).filter(
        EmpresaObligacion.empresa_id.in_(ids),
        EmpresaObligacion.regla_vencimiento == "cronograma_sunat",
    ):
        (obligaciones if activa else apagadas).add((eid, tipo))
    # Apagada a mano ("no esta obligada") y sin otra activa: no se controla
    # aunque SUNAT tenga declaraciones viejas de ese formulario.
    apagadas -= obligaciones
    vencimientos = {
        (periodo, grupo): fecha
        for periodo, grupo, fecha in db.query(
            CronogramaVencimiento.periodo_tributario, CronogramaVencimiento.grupo, CronogramaVencimiento.fecha_vencimiento
        ).filter(
            CronogramaVencimiento.tipo == "mensual",
            CronogramaVencimiento.periodo_tributario.like(f"{anio_elegido}-%"),
        )
    }
    en_curso = {
        eid for (eid,) in db.query(ConsultaDeclaracionesJob.empresa_id).filter(
            ConsultaDeclaracionesJob.empresa_id.in_(ids), ConsultaDeclaracionesJob.estado.in_(ESTADOS_EN_CURSO)
        )
    }
    ultimo_job: dict[str, ConsultaDeclaracionesJob] = {}
    ultima_lectura_ok = {}
    for job in (
        db.query(ConsultaDeclaracionesJob)
        .filter(ConsultaDeclaracionesJob.empresa_id.in_(ids), ConsultaDeclaracionesJob.estado.in_(("completado", "error")))
        .order_by(ConsultaDeclaracionesJob.creado_en)
    ):
        ultimo_job[job.empresa_id] = job
        if job.estado == "completado":
            ultima_lectura_ok[job.empresa_id] = job.finalizado_en

    filas = []
    for e in empresas:
        grupo = grupo_para_empresa(e.ruc, e.es_buen_contribuyente)
        periodos = []
        for mes in range(1, 13):
            periodo = f"{anio_elegido}-{mes:02d}"
            formularios = por_empresa.get(e.id, {}).get(periodo, [])
            vence = vencimientos.get((periodo, grupo))
            if formularios or vence is not None:
                periodos.append(DeclaracionPeriodoItem(
                    periodo=periodo,
                    vence_el=vence,
                    formularios=[DeclaracionItem.model_validate(d) for d in formularios],
                ))
        obligado_desde = {}
        no_controlados = []
        for form, tipo_obligacion in FORMULARIOS_CONTROLADOS.items():
            if (e.id, tipo_obligacion) in apagadas:
                obligado_desde[form] = None
                no_controlados.append(form)
                continue
            desde = primer_periodo.get((e.id, form))
            obligado_desde[form] = desde or (SIEMPRE if (e.id, tipo_obligacion) in obligaciones else None)
        job = ultimo_job.get(e.id)
        filas.append(CumplimientoDeclaracionesFila(
            empresa_id=e.id,
            ruc=e.ruc,
            razon_social=e.razon_social,
            periodos=periodos,
            obligado_desde=obligado_desde,
            formularios_no_controlados=no_controlados,
            actualizado_en=ultima_lectura_ok.get(e.id),
            consulta_en_curso=e.id in en_curso,
            ultimo_error=job.error if job is not None and job.estado == "error" else None,
        ))

    return CumplimientoDeclaracionesResponse(
        anio=anio_elegido,
        anios_disponibles=anios,
        ultimo_periodo_consultable=ultimo,
        filas=filas,
    )


@router.post("/empresas/{empresa_id}/declaraciones/control")
def controlar_formulario(
    empresa_id: str,
    datos: ControlFormularioRequest,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """"No esta obligada" / "Volver a controlar" un formulario (0621 o 0601) para una empresa."""
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    if datos.formulario not in FORMULARIOS_CONTROLADOS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Formulario no controlado")
    tareas_borradas = cambiar_control_formulario(db, empresa.id, datos.formulario, datos.controlar)
    db.commit()
    return {"formulario": datos.formulario, "controlar": datos.controlar, "tareas_borradas": tareas_borradas}


@router.post("/cumplimiento/declaraciones/consultar-todas")
def consultar_declaraciones_todas(
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """Encola la lectura de declaraciones de todas las empresas visibles, espaciadas como la consulta masiva."""
    return encolar_lecturas(
        db, _empresas_cumplimiento(db, usuario), ConsultaDeclaracionesJob, ejecutar_consulta_declaraciones,
        solicitado_por=usuario.id,
    )
