"""
Modulo de Tareas/Agenda: configuracion de que obligaciones tiene cada
empresa (Planilla/AFP/SBS/otro -- no todas tienen todas) + gestion de las
tareas concretas generadas a partir de esas reglas, mas tareas sueltas
creadas a mano. Ver app/tareas.py para la logica de generacion.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Usuario, Empresa, EmpresaObligacion, TareaObligacion, MensajeBuzon
from app.deps import get_usuario_actual
from app.schemas import (
    EmpresaObligacionCreate,
    EmpresaObligacionUpdate,
    EmpresaObligacionResponse,
    TareaObligacionResponse,
    TareaObligacionUpdate,
    TareaObligacionCreate,
    GenerarTareasResponse,
    AvancePorTipo,
    AvanceCumplimientoResponse,
)
from app import tareas as tareas_logic
from app.acceso import filtrar_empresas_visibles, obtener_empresa_visible

logger = logging.getLogger("app.routers.tareas")

router = APIRouter(tags=["tareas"])


def _con_utc(momento):
    # SQLite (pruebas) devuelve datetimes "naive" aunque la columna sea
    # DateTime(timezone=True); Postgres (produccion) los devuelve con
    # tzinfo. Sin normalizar esto, comparar un naive con uno aware revienta
    # con TypeError.
    if momento is not None and momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento

ETIQUETAS_TIPO_AVANCE = {
    "igv_renta": "IGV-Renta",
    "planilla": "Planilla",
    "afp": "AFP",
    "sbs": "Reporte SBS",
    "cts": "CTS",
    "itan": "ITAN",
    "sire": "SIRE",
    "otro": "Otro",
}


def _a_respuesta_tarea(tarea: TareaObligacion, empresa: Empresa) -> TareaObligacionResponse:
    return TareaObligacionResponse(
        id=tarea.id,
        empresa_id=empresa.id,
        empresa_ruc=empresa.ruc,
        empresa_razon_social=empresa.razon_social,
        empresa_obligacion_id=tarea.empresa_obligacion_id,
        mensaje_buzon_id=tarea.mensaje_buzon_id,
        empresa_asignado_a_usuario_id=empresa.asignado_a_usuario_id,
        titulo=tarea.titulo,
        tipo=tarea.tipo,
        periodo=tarea.periodo,
        fecha_vencimiento=tarea.fecha_vencimiento,
        estado=tarea.estado,
        prioridad=tarea.prioridad,
        proceso=tarea.proceso,
        fecha_completado=tarea.fecha_completado,
        observaciones=tarea.observaciones,
        creado_en=tarea.creado_en,
    )


# ---- Configuracion de obligaciones por empresa ----


def _generar_mes_actual_silencioso(db: Session, tenant_id: str) -> None:
    """
    A pedido: crear o reactivar una obligacion generaba la fila en
    EmpresaObligacion pero la tarea del mes solo aparecia si alguien se
    acordaba de apretar "Generar tareas del mes" -- confuso, porque parecia
    que la obligacion "no hacia nada" (no aparecia en Tareas ni en el
    Calendario) hasta ese click manual. Ahora se dispara sola, para el mes
    actual, justo despues de crear/activar una obligacion. Idempotente
    (ver tareas_logic.generar_tareas_mes) y nunca debe tumbar la operacion
    que la disparo -- si falla, se loguea y el usuario igual puede generarla
    a mano despues con el boton de siempre.
    """
    try:
        hoy = datetime.now(timezone.utc)
        tareas_logic.generar_tareas_mes(db, tenant_id, hoy.year, hoy.month)
    except Exception:
        logger.exception("No se pudieron generar las tareas del mes actual tras crear/activar una obligacion")


@router.get("/empresas/{empresa_id}/obligaciones", response_model=list[EmpresaObligacionResponse])
def listar_obligaciones(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    return (
        db.query(EmpresaObligacion)
        .filter(EmpresaObligacion.empresa_id == empresa.id)
        .order_by(EmpresaObligacion.creado_en.asc())
        .all()
    )


@router.post("/empresas/{empresa_id}/obligaciones", response_model=EmpresaObligacionResponse, status_code=status.HTTP_201_CREATED)
def crear_obligacion(
    empresa_id: str,
    data: EmpresaObligacionCreate,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    obligacion = EmpresaObligacion(empresa_id=empresa.id, **data.model_dump())
    db.add(obligacion)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una obligacion con ese tipo y nombre para esta empresa",
        )
    db.refresh(obligacion)
    _generar_mes_actual_silencioso(db, usuario.tenant_id)
    return obligacion


@router.patch("/obligaciones/{obligacion_id}", response_model=EmpresaObligacionResponse)
def actualizar_obligacion(
    obligacion_id: str,
    data: EmpresaObligacionUpdate,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    obligacion = (
        filtrar_empresas_visibles(
            db.query(EmpresaObligacion).join(Empresa, Empresa.id == EmpresaObligacion.empresa_id), usuario
        )
        .filter(EmpresaObligacion.id == obligacion_id)
        .first()
    )
    if not obligacion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Obligacion no encontrada")
    for campo, valor in data.model_dump(exclude_unset=True).items():
        setattr(obligacion, campo, valor)
    db.commit()
    db.refresh(obligacion)
    _generar_mes_actual_silencioso(db, usuario.tenant_id)
    return obligacion


@router.delete("/obligaciones/{obligacion_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_obligacion(
    obligacion_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    obligacion = (
        filtrar_empresas_visibles(
            db.query(EmpresaObligacion).join(Empresa, Empresa.id == EmpresaObligacion.empresa_id), usuario
        )
        .filter(EmpresaObligacion.id == obligacion_id)
        .first()
    )
    if not obligacion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Obligacion no encontrada")
    db.delete(obligacion)
    db.commit()


# ---- Tareas concretas ----


@router.get("/tareas", response_model=list[TareaObligacionResponse])
def listar_tareas_endpoint(
    estado: str | None = None,
    empresa_id: str | None = None,
    periodo: str | None = None,
    # Cartera: filtrar por el usuario asignado a la EMPRESA de la tarea (no
    # hay un campo de asignacion en la tarea misma -- se hereda de la
    # empresa, ver TareaObligacionResponse.empresa_asignado_a_usuario_id).
    asignado_a_usuario_id: str | None = None,
    # Rango de fechas, para que el calendario de /cronograma pueda pedir
    # "las tareas con vencimiento en este mes" ademas del cronograma
    # oficial -- independiente de `periodo` (que es el periodo TRIBUTARIO,
    # no aplica a una tarea suelta creada desde una notificacion).
    fecha_desde: datetime | None = None,
    fecha_hasta: datetime | None = None,
    mensaje_buzon_id: str | None = None,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    query = filtrar_empresas_visibles(
        db.query(TareaObligacion, Empresa).join(Empresa, Empresa.id == TareaObligacion.empresa_id), usuario
    )
    if estado == "vencida":
        # No es un valor real de TareaObligacion.estado -- una tarea
        # "vencida" es cualquier pendiente cuya fecha ya paso. Se traduce
        # aca en vez de guardar un estado aparte, para no tener que ir
        # actualizando tareas viejas dia a dia solo para que "se pongan
        # vencidas" solas.
        query = query.filter(
            TareaObligacion.estado == "pendiente",
            TareaObligacion.fecha_vencimiento < datetime.now(timezone.utc),
        )
    elif estado:
        query = query.filter(TareaObligacion.estado == estado)
    if empresa_id:
        query = query.filter(TareaObligacion.empresa_id == empresa_id)
    if periodo:
        query = query.filter(TareaObligacion.periodo == periodo)
    if asignado_a_usuario_id:
        query = query.filter(Empresa.asignado_a_usuario_id == asignado_a_usuario_id)
    if fecha_desde:
        query = query.filter(TareaObligacion.fecha_vencimiento >= fecha_desde)
    if fecha_hasta:
        query = query.filter(TareaObligacion.fecha_vencimiento < fecha_hasta)
    if mensaje_buzon_id:
        query = query.filter(TareaObligacion.mensaje_buzon_id == mensaje_buzon_id)
    # Las tareas sin fecha (regla manual todavia sin cargar) van al final,
    # no primero -- sqlite y postgres ordenan NULL distinto por defecto,
    # asi que se fuerza con un criterio explicito en vez de confiar en el
    # comportamiento default de cada motor.
    filas = query.order_by(
        TareaObligacion.fecha_vencimiento.is_(None), TareaObligacion.fecha_vencimiento.asc()
    ).all()
    return [_a_respuesta_tarea(tarea, empresa) for tarea, empresa in filas]


@router.post("/tareas", response_model=TareaObligacionResponse, status_code=status.HTTP_201_CREATED)
def crear_tarea_manual(
    data: TareaObligacionCreate,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(data.empresa_id, usuario, db)

    if data.mensaje_buzon_id:
        mensaje = (
            db.query(MensajeBuzon)
            .filter(MensajeBuzon.id == data.mensaje_buzon_id, MensajeBuzon.empresa_id == empresa.id)
            .first()
        )
        if not mensaje:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El mensaje no existe o no pertenece a esta empresa",
            )

    tarea = TareaObligacion(
        empresa_id=empresa.id,
        titulo=data.titulo,
        tipo=data.tipo,
        fecha_vencimiento=data.fecha_vencimiento,
        prioridad=data.prioridad,
        observaciones=data.observaciones,
        mensaje_buzon_id=data.mensaje_buzon_id,
        proceso="manual",
    )
    db.add(tarea)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta notificacion ya tiene una tarea creada",
        )
    db.refresh(tarea)
    return _a_respuesta_tarea(tarea, empresa)


@router.patch("/tareas/{tarea_id}", response_model=TareaObligacionResponse)
def actualizar_tarea(
    tarea_id: str,
    data: TareaObligacionUpdate,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    fila = (
        filtrar_empresas_visibles(
            db.query(TareaObligacion, Empresa).join(Empresa, Empresa.id == TareaObligacion.empresa_id), usuario
        )
        .filter(TareaObligacion.id == tarea_id)
        .first()
    )
    if not fila:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    tarea, empresa = fila
    cambios = data.model_dump(exclude_unset=True)
    if "estado" in cambios:
        tarea.estado = cambios["estado"]
        tarea.fecha_completado = datetime.now(timezone.utc) if cambios["estado"] == "completado" else None
    if "prioridad" in cambios:
        tarea.prioridad = cambios["prioridad"]
    if "fecha_vencimiento" in cambios:
        tarea.fecha_vencimiento = cambios["fecha_vencimiento"]
    if "observaciones" in cambios:
        tarea.observaciones = cambios["observaciones"]
    db.commit()
    db.refresh(tarea)
    return _a_respuesta_tarea(tarea, empresa)


@router.delete("/tareas/{tarea_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_tarea(
    tarea_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    fila = (
        filtrar_empresas_visibles(
            db.query(TareaObligacion).join(Empresa, Empresa.id == TareaObligacion.empresa_id), usuario
        )
        .filter(TareaObligacion.id == tarea_id)
        .first()
    )
    if not fila:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    db.delete(fila)
    db.commit()


@router.post("/tareas/generar", response_model=GenerarTareasResponse)
def generar_tareas(
    anio: int | None = None,
    mes: int | None = None,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Genera las tareas del periodo pedido (por defecto, el mes actual) para
    todas las obligaciones activas de las empresas del tenant -- idempotente,
    se puede apretar el boton "Generar vencimientos" del frontend las veces
    que haga falta sin duplicar nada.
    """
    hoy = datetime.now(timezone.utc)
    anio_objetivo = anio or hoy.year
    mes_objetivo = mes or hoy.month
    if not (1 <= mes_objetivo <= 12):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="mes debe estar entre 1 y 12")
    resultado = tareas_logic.generar_tareas_mes(db, usuario.tenant_id, anio_objetivo, mes_objetivo)
    return GenerarTareasResponse(**resultado)


@router.get("/tareas/avance-cumplimiento", response_model=AvanceCumplimientoResponse)
def avance_cumplimiento(
    periodo: str | None = None,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Panel "Avance de Cumplimiento" del Dashboard: para el periodo pedido
    (por defecto el mes actual, formato "YYYY-MM"), cuenta cuantas
    TareaObligacion hay por tipo (IGV-Renta/Planilla/AFP/Reporte SBS/CTS/
    ITAN/Otro), cuantas ya estan completadas y cuantas estan vencidas
    (pendientes con fecha ya pasada). Cubre cualquier obligacion que
    genere tareas -- incluido el cronograma general de IGV-Renta/PLAME,
    que desde que se autogeneran sus tareas (ver
    app.routers.empresas._crear_obligaciones_por_defecto) tambien se
    puede marcar como completada igual que cualquier otra.
    """
    hoy = datetime.now(timezone.utc)
    periodo_objetivo = periodo or f"{hoy.year:04d}-{hoy.month:02d}"

    # Se cuenta en Python en vez de un GROUP BY con suma condicional --
    # func.sum() de una comparacion booleana no es portable entre SQLite y
    # Postgres sin trucos especificos de cada motor, y el volumen de tareas
    # por tenant no amerita esa complejidad.
    tareas_del_periodo = (
        filtrar_empresas_visibles(
            db.query(TareaObligacion.tipo, TareaObligacion.estado, TareaObligacion.fecha_vencimiento).join(
                Empresa, Empresa.id == TareaObligacion.empresa_id
            ),
            usuario,
        )
        .filter(TareaObligacion.periodo == periodo_objetivo)
        .all()
    )

    acumulado: dict[str, dict[str, int]] = {}
    for tipo, estado, fecha_vencimiento in tareas_del_periodo:
        acc = acumulado.setdefault(tipo, {"total": 0, "completados": 0, "vencidas": 0})
        acc["total"] += 1
        if estado == "completado":
            acc["completados"] += 1
        elif estado == "pendiente" and fecha_vencimiento is not None and _con_utc(fecha_vencimiento) < hoy:
            acc["vencidas"] += 1

    por_tipo = []
    total_general = {"total": 0, "completados": 0, "vencidas": 0}
    for tipo in sorted(acumulado.keys()):
        acc = acumulado[tipo]
        avance = round((acc["completados"] / acc["total"]) * 100, 1) if acc["total"] else 0.0
        por_tipo.append(AvancePorTipo(
            tipo=ETIQUETAS_TIPO_AVANCE.get(tipo, tipo.title()),
            total=acc["total"],
            completados=acc["completados"],
            vencidas=acc["vencidas"],
            avance=avance,
        ))
        total_general["total"] += acc["total"]
        total_general["completados"] += acc["completados"]
        total_general["vencidas"] += acc["vencidas"]

    avance_total = (
        round((total_general["completados"] / total_general["total"]) * 100, 1)
        if total_general["total"] else 0.0
    )

    return AvanceCumplimientoResponse(
        periodo=periodo_objetivo,
        por_tipo=por_tipo,
        total=AvancePorTipo(
            tipo="Total",
            total=total_general["total"],
            completados=total_general["completados"],
            vencidas=total_general["vencidas"],
            avance=avance_total,
        ),
    )
