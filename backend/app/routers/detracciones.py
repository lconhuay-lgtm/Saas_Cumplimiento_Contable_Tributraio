"""
Detracciones: "Consulta de Pago de Detracciones" de SUNAT (Mis Declaraciones y
Pagos > Consultas > Consultas de Presentacion y Pago), para la pestana
"Detracciones" del modulo Cumplimiento. El usuario elige la empresa y los
mismos criterios de la pantalla de SUNAT (fechas de pago o periodo, tipo de
cuenta, tipo de pago); el robot hace la busqueda y los depositos quedan
guardados como historial de la empresa.
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ConsultaDetraccionesJob, DetraccionCobertura, DetraccionPago, Usuario
from app.cumplimiento import ESTADOS_EN_CURSO
from app.schemas import (
    ConsultaDetraccionesJobResponse, ConsultaDetraccionesRequest, DetraccionCoberturaItem, DetraccionItem,
    DetraccionesEmpresaResponse,
)
from app.deps import get_usuario_actual
from app.queue_conn import cola_consultas
from app.jobs import ejecutar_consulta_detracciones
from app.rate_limit import verificar_limite_ruc, LimiteExcedido
from app.acceso import obtener_empresa_visible

router = APIRouter(tags=["detracciones"])

TIPOS_CUENTA = ("1", "2", "3")
TIPOS_PAGO = ("pagosIndividuales", "pagosMasivos", "pagosTransPasajeros")
# Cada 30 dias es una consulta a SUNAT: un anio son 13, todavia rapido.
DIAS_MAXIMOS_BUSQUEDA = 366
_ZONA_LIMA = timezone(timedelta(hours=-5))


def _validar(datos: ConsultaDetraccionesRequest) -> None:
    def rechazar(motivo: str):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=motivo)

    if not datos.tipos_cuenta or any(t not in TIPOS_CUENTA for t in datos.tipos_cuenta):
        rechazar("Tipo de cuenta no valido")
    if not datos.tipos_pago or any(t not in TIPOS_PAGO for t in datos.tipos_pago):
        rechazar("Tipo de pago no valido")
    if datos.periodo:
        try:
            datetime.strptime(datos.periodo, "%Y-%m")
        except ValueError:
            rechazar("El periodo debe tener la forma AAAA-MM")
        return
    if not datos.fecha_desde or not datos.fecha_hasta:
        rechazar("Indica las fechas de pago (desde y hasta) o un periodo tributario")
    if datos.fecha_desde > datos.fecha_hasta:
        rechazar("La fecha 'desde' es posterior a la fecha 'hasta'")
    if datos.fecha_hasta > datetime.now(_ZONA_LIMA).date():
        rechazar("La fecha 'hasta' no puede ser posterior a hoy")
    if (datos.fecha_hasta - datos.fecha_desde).days > DIAS_MAXIMOS_BUSQUEDA:
        rechazar("Busca como maximo un anio de pagos a la vez")


@router.post(
    "/empresas/{empresa_id}/detracciones/consultar",
    response_model=ConsultaDetraccionesJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def consultar_detracciones(
    empresa_id: str,
    datos: ConsultaDetraccionesRequest,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    _validar(datos)
    en_curso = (
        db.query(ConsultaDetraccionesJob)
        .filter(ConsultaDetraccionesJob.empresa_id == empresa.id, ConsultaDetraccionesJob.estado.in_(ESTADOS_EN_CURSO))
        .first()
    )
    if en_curso:
        return en_curso
    try:
        verificar_limite_ruc(empresa.ruc)
    except LimiteExcedido as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    job = ConsultaDetraccionesJob(
        empresa_id=empresa.id,
        solicitado_por=usuario.id,
        estado="pendiente",
        periodo=datos.periodo or None,
        fecha_desde=None if datos.periodo else datos.fecha_desde,
        fecha_hasta=None if datos.periodo else datos.fecha_hasta,
        tipos_cuenta=",".join(dict.fromkeys(datos.tipos_cuenta)),
        tipos_pago=",".join(dict.fromkeys(datos.tipos_pago)),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    cola_consultas.enqueue(ejecutar_consulta_detracciones, job.id, job_timeout="15m", at_front=True)
    return job


@router.get("/empresas/{empresa_id}/detracciones", response_model=DetraccionesEmpresaResponse)
def detracciones_empresa(
    empresa_id: str,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    periodo: str | None = None,
    tipo_cuenta: str | None = None,
    tipo_pago: str | None = None,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """Depositos ya guardados de la empresa con los mismos filtros de la busqueda, mas el estado de la ultima busqueda."""
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    query = db.query(DetraccionPago).filter(DetraccionPago.empresa_id == empresa.id)
    if periodo:
        query = query.filter(DetraccionPago.periodo == periodo)
    else:
        if fecha_desde:
            query = query.filter(DetraccionPago.fecha_pago >= fecha_desde)
        if fecha_hasta:
            query = query.filter(DetraccionPago.fecha_pago <= fecha_hasta)
    if tipo_cuenta:
        query = query.filter(DetraccionPago.tipo_cuenta == tipo_cuenta)
    if tipo_pago:
        query = query.filter(DetraccionPago.tipo_pago == tipo_pago)
    depositos = query.order_by(DetraccionPago.fecha_pago.desc(), DetraccionPago.num_constancia.desc()).all()

    busqueda = (
        db.query(ConsultaDetraccionesJob)
        .filter(ConsultaDetraccionesJob.empresa_id == empresa.id, ConsultaDetraccionesJob.estado.in_(ESTADOS_EN_CURSO))
        .order_by(ConsultaDetraccionesJob.creado_en.desc())
        .first()
    ) or (
        db.query(ConsultaDetraccionesJob)
        .filter(ConsultaDetraccionesJob.empresa_id == empresa.id)
        .order_by(ConsultaDetraccionesJob.creado_en.desc())
        .first()
    )
    cobertura = db.get(DetraccionCobertura, empresa.id)
    return DetraccionesEmpresaResponse(
        cobertura=DetraccionCoberturaItem.model_validate(cobertura) if cobertura else None,
        empresa_id=empresa.id,
        ruc=empresa.ruc,
        razon_social=empresa.razon_social,
        depositos=[DetraccionItem.model_validate(d) for d in depositos],
        busqueda=ConsultaDetraccionesJobResponse.model_validate(busqueda) if busqueda else None,
    )
