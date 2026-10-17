"""Resumen general del tenant."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Empresa, MensajeBuzon, ConsultaJob, Usuario, TareaObligacion
from app.schemas import (
    DashboardResumen,
    EmpresaPendienteResumen,
    ActividadRecienteItem,
    CambioDomicilioItem,
    CambioEstadoContribuyenteItem,
    ProximoVencimientoItem,
)
from app.deps import get_usuario_actual
from app.cronograma_sunat import proximos_vencimientos_por_tenant
from app.acceso import filtrar_empresas_visibles

# Modulo de cronograma SUNAT: cuantos dias adelante mostrar un vencimiento
# como "proximo" en el Dashboard -- 15 dias da tiempo de sobra para
# reaccionar sin mostrar vencimientos tan lejanos que pierdan urgencia.
DIAS_PROXIMO_VENCIMIENTO = 15

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Ventana de tiempo para mostrar un cambio de condicion de domicilio (o de
# estado del contribuyente) como "reciente" en el Dashboard. Generosa a
# proposito: ninguno de los dos cambia seguido, asi que no hay riesgo de
# saturar la seccion, y conviene que el aviso no desaparezca a las pocas
# horas.
DIAS_CAMBIO_DOMICILIO_RECIENTE = 30
DIAS_CAMBIO_ESTADO_CONTRIBUYENTE_RECIENTE = 30


@router.get("/resumen", response_model=DashboardResumen)
def resumen(
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresas = filtrar_empresas_visibles(db.query(Empresa), usuario).all()
    empresas_por_id = {e.id: e for e in empresas}
    empresas_activas = sum(1 for e in empresas if e.activo)

    pendientes_por_empresa: dict[str, int] = {}
    if empresas:
        filas = (
            db.query(MensajeBuzon.empresa_id, func.count(MensajeBuzon.id))
            .filter(MensajeBuzon.empresa_id.in_(list(empresas_por_id.keys())), MensajeBuzon.leido.is_(False))
            .group_by(MensajeBuzon.empresa_id)
            .all()
        )
        pendientes_por_empresa = {empresa_id: total for empresa_id, total in filas}

    mensajes_hoy_por_empresa: dict[str, int] = {}
    if empresas:
        inicio_de_hoy = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        filas_hoy = (
            db.query(MensajeBuzon.empresa_id, func.count(MensajeBuzon.id))
            .filter(
                MensajeBuzon.empresa_id.in_(list(empresas_por_id.keys())),
                MensajeBuzon.descubierto_en >= inicio_de_hoy,
            )
            .group_by(MensajeBuzon.empresa_id)
            .all()
        )
        mensajes_hoy_por_empresa = {empresa_id: total for empresa_id, total in filas_hoy}

    empresas_con_pendientes = sorted(
        (
            EmpresaPendienteResumen(
                id=e.id,
                ruc=e.ruc,
                razon_social=e.razon_social,
                pendientes=pendientes_por_empresa.get(e.id, 0),
            )
            for e in empresas
            if pendientes_por_empresa.get(e.id, 0) > 0
        ),
        key=lambda item: item.pendientes,
        reverse=True,
    )

    jobs_recientes = (
        filtrar_empresas_visibles(
            db.query(ConsultaJob).join(Empresa, Empresa.id == ConsultaJob.empresa_id), usuario
        )
        .filter(ConsultaJob.finalizado_en.isnot(None))
        .order_by(ConsultaJob.finalizado_en.desc())
        .limit(10)
        .all()
    )
    actividad_reciente = [
        ActividadRecienteItem(
            empresa_id=job.empresa_id,
            empresa_ruc=empresas_por_id[job.empresa_id].ruc,
            empresa_razon_social=empresas_por_id[job.empresa_id].razon_social,
            estado=job.estado,
            mensajes_nuevos=job.mensajes_nuevos,
            finalizado_en=job.finalizado_en,
            error=job.error,
        )
        for job in jobs_recientes
        if job.empresa_id in empresas_por_id
    ]

    def _con_utc(momento):
        # SQLite (pruebas) devuelve datetimes "naive" aunque la columna sea
        # DateTime(timezone=True); Postgres (produccion) los devuelve con
        # tzinfo. Sin normalizar esto, comparar un naive con uno aware
        # revienta con TypeError.
        if momento is not None and momento.tzinfo is None:
            return momento.replace(tzinfo=timezone.utc)
        return momento

    desde_domicilio = datetime.now(timezone.utc) - timedelta(days=DIAS_CAMBIO_DOMICILIO_RECIENTE)
    cambios_domicilio_recientes = sorted(
        (
            CambioDomicilioItem(
                empresa_id=e.id,
                empresa_ruc=e.ruc,
                empresa_razon_social=e.razon_social,
                condicion_anterior=e.condicion_domicilio_anterior,
                condicion_actual=e.condicion_domicilio,
                actualizada_en=_con_utc(e.condicion_domicilio_actualizada_en),
            )
            for e in empresas
            if e.condicion_domicilio_actualizada_en is not None
            and _con_utc(e.condicion_domicilio_actualizada_en) >= desde_domicilio
        ),
        key=lambda item: item.actualizada_en,
        reverse=True,
    )

    desde_estado_contribuyente = datetime.now(timezone.utc) - timedelta(days=DIAS_CAMBIO_ESTADO_CONTRIBUYENTE_RECIENTE)
    cambios_estado_contribuyente_recientes = sorted(
        (
            CambioEstadoContribuyenteItem(
                empresa_id=e.id,
                empresa_ruc=e.ruc,
                empresa_razon_social=e.razon_social,
                estado_anterior=e.estado_contribuyente_anterior,
                estado_actual=e.estado_contribuyente,
                actualizada_en=_con_utc(e.estado_contribuyente_actualizado_en),
            )
            for e in empresas
            if e.estado_contribuyente_actualizado_en is not None
            and _con_utc(e.estado_contribuyente_actualizado_en) >= desde_estado_contribuyente
        ),
        key=lambda item: item.actualizada_en,
        reverse=True,
    )

    proximos_vencimientos = [
        ProximoVencimientoItem(**v)
        for v in proximos_vencimientos_por_tenant(db, usuario.tenant_id, DIAS_PROXIMO_VENCIMIENTO, usuario)
    ]

    # Modulo de Tareas/Agenda: cuantas tareas pendientes ya pasaron su fecha
    # de vencimiento sin completarse, de CUALQUIER periodo -- a diferencia
    # del panel "Avance de Cumplimiento" (que solo mira un periodo a la
    # vez), esto es el numero que importa ver de un vistazo en el
    # Dashboard para saber si hay algo atrasado sin tener que ir a revisar
    # mes por mes.
    tareas_vencidas = (
        filtrar_empresas_visibles(
            db.query(TareaObligacion).join(Empresa, Empresa.id == TareaObligacion.empresa_id), usuario
        )
        .filter(TareaObligacion.estado == "pendiente", TareaObligacion.fecha_vencimiento < datetime.now(timezone.utc))
        .count()
    )

    return DashboardResumen(
        empresas_activas=empresas_activas,
        empresas_totales=len(empresas),
        pendientes_totales=sum(pendientes_por_empresa.values()),
        mensajes_hoy_totales=sum(mensajes_hoy_por_empresa.values()),
        empresas_con_novedades_hoy=sum(1 for v in mensajes_hoy_por_empresa.values() if v > 0),
        empresas_con_pendientes=empresas_con_pendientes,
        actividad_reciente=actividad_reciente,
        cambios_domicilio_recientes=cambios_domicilio_recientes,
        cambios_estado_contribuyente_recientes=cambios_estado_contribuyente_recientes,
        proximos_vencimientos=proximos_vencimientos,
        tareas_vencidas=tareas_vencidas,
    )
