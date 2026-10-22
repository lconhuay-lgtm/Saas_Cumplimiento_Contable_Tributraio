"""
Modulo de Tareas/Agenda: genera y gestiona las tareas concretas
(TareaObligacion) a partir de las obligaciones configurables por empresa
(EmpresaObligacion) -- ver app.models (docstrings de esas dos clases) para
el diseno completo de las reglas de vencimiento. Ademas de las tareas
generadas, el usuario puede crear tareas sueltas a mano (sin
empresa_obligacion_id) para pendientes puntuales.
"""
import calendar
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    Empresa, EmpresaObligacion, TareaObligacion, CronogramaVencimiento, DeclaracionSunat, SireEstadoPeriodo,
)
from app.cronograma_sunat import grupo_para_empresa, empresas_para_cronograma

logger = logging.getLogger("app.tareas")

ETIQUETAS_TIPO = {
    "igv_renta": "IGV-Renta",
    "planilla": "Planilla",
    "afp": "AFP",
    "sbs": "Reporte SBS",
    "cts": "CTS",
    "itan": "ITAN",
    "sire": "SIRE",
    "deuda": "Deuda SUNAT",
    "otro": "Otro",
}


def _con_utc(momento):
    # Mismo patron que en cronograma_sunat.py y los routers -- SQLite
    # (pruebas) devuelve datetimes naive aunque la columna sea
    # DateTime(timezone=True); Postgres (produccion) los devuelve con tzinfo.
    if momento is not None and momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


def _fecha_cronograma_sunat(db: Session, empresa: Empresa, anio: int, mes: int) -> datetime | None:
    """
    Planilla y AFP se declaran junto con la PLAME (confirmado: la PLAME
    incluye remuneraciones + aportes AFP/ONP/EsSalud/renta 5ta en un solo
    envio) -- comparten EXACTAMENTE la misma fecha que el cronograma
    general de IGV-Renta/PLAME que ya usa el modulo Cronograma para el
    periodo pedido.
    """
    periodo = f"{anio:04d}-{mes:02d}"
    grupo = grupo_para_empresa(empresa.ruc, empresa.es_buen_contribuyente)
    fila = (
        db.query(CronogramaVencimiento)
        .filter(
            CronogramaVencimiento.periodo_tributario == periodo,
            CronogramaVencimiento.grupo == grupo,
            CronogramaVencimiento.tipo == "mensual",
        )
        .first()
    )
    return _con_utc(fila.fecha_vencimiento) if fila else None


def _fecha_cronograma_sire(db: Session, empresa: Empresa, anio: int, mes: int) -> datetime | None:
    """Misma logica que _fecha_cronograma_sunat, contra el cronograma de Atraso de Registros Electronicos (ver app.cronograma_sire)."""
    periodo = f"{anio:04d}-{mes:02d}"
    grupo = grupo_para_empresa(empresa.ruc, empresa.es_buen_contribuyente)
    fila = (
        db.query(CronogramaVencimiento)
        .filter(
            CronogramaVencimiento.periodo_tributario == periodo,
            CronogramaVencimiento.grupo == grupo,
            CronogramaVencimiento.tipo == "sire",
        )
        .first()
    )
    return _con_utc(fila.fecha_vencimiento) if fila else None


def _parsear_meses_activos(valor: str | None) -> set[int] | None:
    """"5,11" -> {5, 11}. None/vacio -> None (sin filtro, todos los meses)."""
    if not valor:
        return None
    return {int(m) for m in valor.split(",") if m.strip()}


def _fecha_dia_fijo(anio: int, mes: int, dia_fijo: int) -> datetime:
    """
    Vencimiento el dia_fijo de anio-mes -- si el mes tiene menos dias que
    dia_fijo (p.ej. dia_fijo=31 en un febrero de 28 dias), se usa el
    ultimo dia real de ese mes en vez de reventar.
    """
    ultimo_dia_mes = calendar.monthrange(anio, mes)[1]
    dia = min(dia_fijo, ultimo_dia_mes)
    return datetime(anio, mes, dia, tzinfo=timezone.utc)


def generar_tareas_mes(db: Session, tenant_id: str, anio: int, mes: int) -> dict:
    """
    Genera (si todavia no existen) las TareaObligacion del periodo anio-mes
    para todas las obligaciones ACTIVAS de las empresas del tenant que
    corresponde considerar (activas, sin baja de oficio -- mismo filtro que
    el modulo Cronograma). Idempotente: si ya existe una tarea para esa
    obligacion+periodo, no la duplica -- se puede llamar de nuevo sin
    miedo (p.ej. el boton "Generar vencimientos" del frontend, o un cron
    mensual mas adelante).
    """
    periodo = f"{anio:04d}-{mes:02d}"
    empresas = empresas_para_cronograma(db, tenant_id)
    if not empresas:
        return {"periodo": periodo, "tareas_creadas": 0, "obligaciones_sin_regla": 0}

    creadas = 0
    sin_regla = 0
    for empresa in empresas:
        obligaciones = (
            db.query(EmpresaObligacion)
            .filter(EmpresaObligacion.empresa_id == empresa.id, EmpresaObligacion.activa.is_(True))
            .all()
        )
        for ob in obligaciones:
            ya_existe = (
                db.query(TareaObligacion)
                .filter(TareaObligacion.empresa_obligacion_id == ob.id, TareaObligacion.periodo == periodo)
                .first()
            )
            if ya_existe:
                continue

            # "dia_fijo_anual" solo genera tarea en SU mes -- las demas
            # reglas generan todos los meses, asi que esta es la unica que
            # necesita saltarse el resto del periodo por completo (ni
            # siquiera cuenta como "sin_regla", no es un error).
            if ob.regla_vencimiento == "dia_fijo_anual" and ob.mes_fijo != mes:
                continue

            # meses_activos (recurrencia flexible: CTS, ITAN en cuotas,
            # bimestral/trimestral/semestral/personalizada) -- filtro
            # adicional sobre cronograma_sunat/dia_fijo_mes, mismo criterio
            # de "no cuenta como sin_regla" que dia_fijo_anual arriba.
            meses_activos = _parsear_meses_activos(ob.meses_activos)
            if meses_activos is not None and mes not in meses_activos:
                continue

            fecha_vencimiento = None
            proceso = "manual"
            if ob.regla_vencimiento == "cronograma_sunat":
                fecha_vencimiento = _fecha_cronograma_sunat(db, empresa, anio, mes)
                proceso = "automatica"
            elif ob.regla_vencimiento == "cronograma_sire":
                fecha_vencimiento = _fecha_cronograma_sire(db, empresa, anio, mes)
                proceso = "automatica"
            elif ob.regla_vencimiento == "dia_fijo_mes" and ob.dia_fijo:
                fecha_vencimiento = _fecha_dia_fijo(anio, mes, ob.dia_fijo)
                proceso = "automatica"
            elif ob.regla_vencimiento == "dia_fijo_anual" and ob.dia_fijo and ob.mes_fijo:
                fecha_vencimiento = _fecha_dia_fijo(anio, mes, ob.dia_fijo)
                proceso = "automatica"
            # regla "manual": fecha_vencimiento queda en None -- el usuario
            # la carga a mano desde la tarea generada (sirve como
            # recordatorio de "esto hay que revisar este mes", aunque
            # todavia no se sepa la fecha exacta).

            if fecha_vencimiento is None and ob.regla_vencimiento not in ("manual",):
                sin_regla += 1
                logger.warning(
                    f"No se pudo calcular fecha de vencimiento para {empresa.ruc} / {ob.nombre} "
                    f"(regla={ob.regla_vencimiento}, periodo={periodo}) -- se salta esta obligacion este mes."
                )
                continue

            etiqueta_tipo = ETIQUETAS_TIPO.get(ob.tipo, ob.tipo.title())
            tarea = TareaObligacion(
                empresa_id=empresa.id,
                empresa_obligacion_id=ob.id,
                titulo=f"{etiqueta_tipo} -- {ob.nombre} ({periodo})",
                tipo=ob.tipo,
                periodo=periodo,
                fecha_vencimiento=fecha_vencimiento,
                fecha_vencimiento_original=fecha_vencimiento,
                proceso=proceso,
                prioridad=ob.prioridad,
            )
            db.add(tarea)
            creadas += 1

    db.commit()
    # Si SUNAT ya registra lo presentado (p. ej. la tarea se genero tarde),
    # la tarea nace completada en vez de quedar pendiente.
    for empresa in empresas:
        sincronizar_tareas_con_sunat(db, empresa.id)
    db.commit()
    logger.info(f"Tareas generadas para {periodo}: {creadas} creada(s), {sin_regla} sin fecha calculable.")
    return {"periodo": periodo, "tareas_creadas": creadas, "obligaciones_sin_regla": sin_regla}


# PLAME: quien la presento en el ultimo anio tiene trabajadores (o
# pensionistas/4ta con retencion) y queda obligada mes a mes.
MESES_PLAME_RECIENTE = 12
NOMBRE_PLAME_DETECTADA = "PLAME -- Planilla (detectada en SUNAT)"


def revisar_obligacion_plame(db: Session, empresa_id: str) -> str | None:
    """
    No todas las empresas declaran PLAME, y hasta ahora dependia de que
    alguien marcara la casilla al registrar la empresa. Con lo que lee
    "Declaracion mensual": si SUNAT registra un 0601 en los ultimos 12
    meses y la empresa no tiene NINGUNA obligacion de planilla, se le crea
    (regla cronograma_sunat, como la de la casilla) para que se generen sus
    tareas y el cuadro la controle. Nunca desactiva ni reactiva una que el
    usuario configuro: si la apago a mano, se respeta. No hace commit.
    Devuelve "creada" o None.
    """
    # Solo cuenta una obligacion de PLAME (tipo planilla que sigue el
    # cronograma de SUNAT): "Planilla mensual"/"Adelanto de quincena" con dia
    # fijo son el pago interno de sueldos, no la declaracion.
    ya_tiene = (
        db.query(EmpresaObligacion.id)
        .filter(
            EmpresaObligacion.empresa_id == empresa_id,
            EmpresaObligacion.tipo == "planilla",
            EmpresaObligacion.regla_vencimiento == "cronograma_sunat",
        )
        .first()
    )
    if ya_tiene:
        return None
    hoy = datetime.now(timezone.utc)
    meses = hoy.year * 12 + hoy.month - 1 - MESES_PLAME_RECIENTE
    desde = f"{meses // 12}-{meses % 12 + 1:02d}"
    reciente = (
        db.query(DeclaracionSunat.id)
        .filter(
            DeclaracionSunat.empresa_id == empresa_id,
            DeclaracionSunat.formulario == "0601",
            DeclaracionSunat.periodo >= desde,
        )
        .first()
    )
    if not reciente:
        return None
    db.add(EmpresaObligacion(
        empresa_id=empresa_id, tipo="planilla", nombre=NOMBRE_PLAME_DETECTADA,
        regla_vencimiento="cronograma_sunat", activa=True,
    ))
    logger.info(f"Empresa {empresa_id}: presenta PLAME en SUNAT y no tenia la obligacion -- creada automaticamente")
    return "creada"


NOMBRE_OBLIGACION_POR_FORMULARIO = {"0621": "IGV-Renta mensual", "0601": NOMBRE_PLAME_DETECTADA}


def cambiar_control_formulario(db: Session, empresa_id: str, formulario: str, controlar: bool) -> int:
    """
    Boton "No esta obligada" / "Volver a controlar" de Declaracion mensual.
    Hay empresas que presentaron alguna PLAME (o un 0621) pero ya no estan
    obligadas: apagar la obligacion (regla cronograma_sunat) hace que el
    cuadro deje de pedirla, que no se generen mas tareas y que la deteccion
    automatica de PLAME no la vuelva a crear. Si no habia obligacion se crea
    una apagada, que es lo que esa deteccion respeta. Al apagar se borran las
    tareas todavia pendientes de esa obligacion (las completadas quedan como
    historial). No hace commit. Devuelve cuantas tareas se borraron.
    """
    tipo = next(t for t, forms in FORMULARIOS_POR_TIPO_TAREA.items() if formulario in forms)
    obligaciones = (
        db.query(EmpresaObligacion)
        .filter(
            EmpresaObligacion.empresa_id == empresa_id,
            EmpresaObligacion.tipo == tipo,
            EmpresaObligacion.regla_vencimiento == "cronograma_sunat",
        )
        .all()
    )
    if not obligaciones:
        db.add(EmpresaObligacion(
            empresa_id=empresa_id, tipo=tipo, nombre=NOMBRE_OBLIGACION_POR_FORMULARIO[formulario],
            regla_vencimiento="cronograma_sunat", activa=controlar,
        ))
        return 0
    if controlar:
        obligaciones[0].activa = True
        return 0
    for ob in obligaciones:
        ob.activa = False
    return (
        db.query(TareaObligacion)
        .filter(
            TareaObligacion.empresa_obligacion_id.in_([ob.id for ob in obligaciones]),
            TareaObligacion.estado == "pendiente",
        )
        .delete(synchronize_session=False)
    )


# Declaracion que, si SUNAT la registra para el periodo, da por cumplida la
# tarea de ese tipo. AFP no esta: se declara en AFPnet, no en SUNAT.
FORMULARIOS_POR_TIPO_TAREA = {"igv_renta": ("0621",), "planilla": ("0601",)}
TIPOS_VERIFICABLES_EN_SUNAT = (*FORMULARIOS_POR_TIPO_TAREA, "sire")


def _fecha_es(d) -> str:
    return d.strftime("%d/%m/%Y")


def sincronizar_tareas_con_sunat(db: Session, empresa_id: str) -> int:
    """
    Completa solas las tareas pendientes de IGV-Renta, Planilla (PLAME) y
    SIRE cuyo periodo SUNAT ya registra como presentado -- con lo que leen
    las pestanas "Declaracion mensual" (DeclaracionSunat) y "SIRE"
    (SireEstadoPeriodo) de Cumplimiento. No hace commit. Devuelve cuantas
    completo.
    """
    # Solo tareas de obligaciones que siguen el cronograma de SUNAT: una
    # "Planilla mensual" con dia fijo es el pago de sueldos, no la PLAME, y
    # no debe darse por cumplida porque se presento el 0601.
    pendientes = (
        db.query(TareaObligacion)
        .join(EmpresaObligacion, EmpresaObligacion.id == TareaObligacion.empresa_obligacion_id)
        .filter(
            TareaObligacion.empresa_id == empresa_id,
            TareaObligacion.estado == "pendiente",
            TareaObligacion.periodo.isnot(None),
            TareaObligacion.tipo.in_(TIPOS_VERIFICABLES_EN_SUNAT),
            TareaObligacion.verificado_sunat_en.is_(None),
            EmpresaObligacion.regla_vencimiento.in_(("cronograma_sunat", "cronograma_sire")),
        )
        .all()
    )
    ahora = datetime.now(timezone.utc)
    completadas = 0
    for tarea in pendientes:
        fecha = None
        detalle = None
        if tarea.tipo in FORMULARIOS_POR_TIPO_TAREA:
            declaracion = (
                db.query(DeclaracionSunat)
                .filter(
                    DeclaracionSunat.empresa_id == empresa_id,
                    DeclaracionSunat.periodo == tarea.periodo,
                    DeclaracionSunat.formulario.in_(FORMULARIOS_POR_TIPO_TAREA[tarea.tipo]),
                )
                .order_by(DeclaracionSunat.fecha_presentacion.asc())
                .first()
            )
            if declaracion is not None:
                if declaracion.fecha_presentacion:
                    d = declaracion.fecha_presentacion
                    fecha = datetime(d.year, d.month, d.day, 17, tzinfo=timezone.utc)
                detalle = (
                    f"SUNAT registra el formulario {declaracion.formulario} (N° de orden {declaracion.num_orden})"
                    + (f" presentado el {_fecha_es(declaracion.fecha_presentacion)}" if declaracion.fecha_presentacion else "")
                )
        else:
            libros = (
                db.query(SireEstadoPeriodo)
                .filter(SireEstadoPeriodo.empresa_id == empresa_id, SireEstadoPeriodo.periodo == tarea.periodo)
                .all()
            )
            if libros and all(l.presentado for l in libros):
                detalle = f"SUNAT registra presentado el SIRE ({', '.join(sorted(l.libro for l in libros))}) del periodo"
        if detalle is None:
            continue
        tarea.estado = "completado"
        tarea.fecha_completado = fecha or ahora
        tarea.verificado_sunat_en = ahora
        nota = f"Completada automaticamente: {detalle}."
        tarea.observaciones = (f"{tarea.observaciones}\n{nota}" if tarea.observaciones else nota)[:2000]
        completadas += 1
    if completadas:
        logger.info(f"Empresa {empresa_id}: {completadas} tarea(s) completada(s) al verificar en SUNAT")
    return completadas
