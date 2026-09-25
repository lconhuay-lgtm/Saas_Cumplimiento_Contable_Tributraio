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

from app.models import Empresa, EmpresaObligacion, TareaObligacion, CronogramaVencimiento
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
                proceso=proceso,
                prioridad=ob.prioridad,
            )
            db.add(tarea)
            creadas += 1

    db.commit()
    logger.info(f"Tareas generadas para {periodo}: {creadas} creada(s), {sin_regla} sin fecha calculable.")
    return {"periodo": periodo, "tareas_creadas": creadas, "obligaciones_sin_regla": sin_regla}
