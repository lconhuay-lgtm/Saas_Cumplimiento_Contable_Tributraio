#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Proceso separado (servicio 'scheduler' en docker-compose.yml) que dispara,
dos veces al dia, el chequeo del buzon y, un rato despues de cada uno, el
correo de resumen. Vive aparte de la API y del worker para que un problema
aqui (p.ej. una excepcion en el cron) no tumbe ninguno de los otros dos.

Los horarios se definen en hora UTC del contenedor -- Peru esta en UTC-5
todo el ano (no tiene horario de verano), asi que por defecto:
  CHEQUEO1_HORA_UTC=16, CHEQUEO1_MINUTO_UTC=0   -> 11:00 hora Peru
  RESUMEN1_HORA_UTC=18, RESUMEN1_MINUTO_UTC=0   -> 13:00 hora Peru (~2h despues,
                                                    deja tiempo a que termine la cola)
  CHEQUEO2_HORA_UTC=0,  CHEQUEO2_MINUTO_UTC=30  -> 19:30 hora Peru
  RESUMEN2_HORA_UTC=2,  RESUMEN2_MINUTO_UTC=30  -> 21:30 hora Peru (~2h despues)
Ajustables por variable de entorno si hace falta.

Punto 6 (panel maestro): CHEQUEO1_*/CHEQUEO2_* de arriba ahora son solo el
FALLBACK de arranque -- la fuente de verdad real es ConfiguracionSistema
(fila "global" en la base, editable en /configuracion sin redeploy, ver
app.rate_limit.horarios_chequeo()). El job "recargar_horarios" relee esa
fila cada RECARGA_HORARIOS_INTERVALO_MIN minutos (5 por defecto) y, si
cambio, reprograma chequeo_1/chequeo_2 en caliente con reschedule_job --
no hace falta reiniciar este contenedor para que un cambio de horario
surta efecto. RESUMEN1_*/RESUMEN2_* siguen siendo fijos por variable de
entorno (fuera del alcance del punto 6, que solo pidio la hora de la
consulta masiva, no la del correo de resumen).

Fase 3 (confiabilidad/observabilidad): ademas de los 4 jobs de arriba, este
mismo proceso dispara el "chequeo canario" cada CANARIO_INTERVALO_MIN
minutos (30 por defecto) -- un login de prueba contra una cuenta
controlada, separado de las consultas de los tenants, para enterarnos de
un cambio en el portal de SUNAT por nuestro propio monitoreo en vez de por
el reclamo de un cliente. No hace nada si no hay ninguna empresa marcada
como es_canario=True (ver app.scheduler_job.ejecutar_chequeo_canario).
"""
import os
import sys
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("scheduler_entry")

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.scheduler_job import encolar_chequeo_nocturno, enviar_resumenes_diarios, ejecutar_chequeo_canario
from app.database import SessionLocal
from app.cronograma_sunat import asegurar_cronograma_vigente
from app.cronograma_sire import asegurar_cronograma_sire_vigente
from app.almacenamiento import limpiar_datos_antiguos
from app.tareas import generar_tareas_mes
from app.rate_limit import horarios_chequeo
from app.models import Tenant

RESUMEN1_HORA_UTC = int(os.environ.get("RESUMEN1_HORA_UTC", "18"))
RESUMEN1_MINUTO_UTC = int(os.environ.get("RESUMEN1_MINUTO_UTC", "0"))

RESUMEN2_HORA_UTC = int(os.environ.get("RESUMEN2_HORA_UTC", "2"))
RESUMEN2_MINUTO_UTC = int(os.environ.get("RESUMEN2_MINUTO_UTC", "30"))

# Punto 6: cada cuantos minutos se relee ConfiguracionSistema para detectar
# un cambio de horario hecho desde el panel maestro (ver job_recargar_horarios).
RECARGA_HORARIOS_INTERVALO_MIN = int(os.environ.get("RECARGA_HORARIOS_INTERVALO_MIN", "5"))

# Ultimo horario aplicado a los jobs chequeo_1/chequeo_2 -- se compara contra
# esto en cada recarga para saber si hace falta reschedule_job (evita
# reprogramar de mas si no cambio nada).
_horario_actual = {"chequeo1_hora": None, "chequeo1_minuto": None, "chequeo2_hora": None, "chequeo2_minuto": None}

# Fase 3: cada cuantos minutos corre el chequeo canario. 30 min es un buen
# equilibrio -- lo bastante seguido para enterarse rapido de un cambio en
# el portal de SUNAT, sin sumarle carga real al sistema (es 1 sola sesion
# de Selenium cada vez, y solo si hay una empresa marcada como canario).
CANARIO_INTERVALO_MIN = int(os.environ.get("CANARIO_INTERVALO_MIN", "30"))


def job_chequeo(etiqueta: str):
    logger.info(f"Disparando chequeo programado ({etiqueta})...")
    try:
        resultado = encolar_chequeo_nocturno()
        logger.info(f"Chequeo ({etiqueta}) encolado: {resultado}")
    except Exception:
        logger.exception(f"Fallo el chequeo programado ({etiqueta})")


def job_resumen(etiqueta: str):
    logger.info(f"Disparando envio de resumenes ({etiqueta})...")
    try:
        resultado = enviar_resumenes_diarios()
        logger.info(f"Resumenes ({etiqueta}) enviados: {resultado}")
    except Exception:
        logger.exception(f"Fallo el envio de resumenes ({etiqueta})")


def job_canario():
    logger.info("Disparando chequeo canario...")
    try:
        resultado = ejecutar_chequeo_canario()
        logger.info(f"Chequeo canario: {resultado}")
    except Exception:
        logger.exception("Fallo el chequeo canario")


def job_recargar_horarios(scheduler):
    """
    Punto 6: relee ConfiguracionSistema (panel maestro) y, si el horario de
    chequeo_1 o chequeo_2 cambio desde la ultima vez, reprograma ese job en
    caliente con reschedule_job -- sin esto, el proceso tendria que
    reiniciarse para que un cambio guardado en /configuracion surta efecto.
    """
    try:
        horarios = horarios_chequeo()
    except Exception:
        logger.exception("No se pudo releer el horario de chequeos, se mantiene el actual")
        return

    if (horarios["chequeo1_hora"], horarios["chequeo1_minuto"]) != (
        _horario_actual["chequeo1_hora"],
        _horario_actual["chequeo1_minuto"],
    ):
        scheduler.reschedule_job(
            "chequeo_1",
            trigger=CronTrigger(hour=horarios["chequeo1_hora"], minute=horarios["chequeo1_minuto"]),
        )
        logger.info(
            f"Horario de chequeo_1 actualizado a {horarios['chequeo1_hora']:02d}:{horarios['chequeo1_minuto']:02d} UTC "
            "(cambio hecho desde el panel maestro)"
        )

    if (horarios["chequeo2_hora"], horarios["chequeo2_minuto"]) != (
        _horario_actual["chequeo2_hora"],
        _horario_actual["chequeo2_minuto"],
    ):
        scheduler.reschedule_job(
            "chequeo_2",
            trigger=CronTrigger(hour=horarios["chequeo2_hora"], minute=horarios["chequeo2_minuto"]),
        )
        logger.info(
            f"Horario de chequeo_2 actualizado a {horarios['chequeo2_hora']:02d}:{horarios['chequeo2_minuto']:02d} UTC "
            "(cambio hecho desde el panel maestro)"
        )

    _horario_actual.update(horarios)


def job_limpieza_diagnosticos():
    """Fase R7: borra capturas de diagnostico y correos de modo prueba viejos -- ver almacenamiento.limpiar_datos_antiguos()."""
    logger.info("Limpiando datos antiguos de diagnostico...")
    try:
        resultado = limpiar_datos_antiguos()
        logger.info(f"Limpieza de datos antiguos: {resultado}")
    except Exception:
        logger.exception("Fallo la limpieza de datos antiguos")


def job_cronograma():
    """
    Modulo de cronograma SUNAT: una vez al dia, se asegura de que el
    cronograma del ejercicio actual (y del siguiente si ya es diciembre)
    este cargado -- idempotente, asi que en los dias normales esto no hace
    ninguna descarga real (ya esta completo), solo confirma que sigue
    estandolo. Ademas del startup del backend (ver app/main.py), este job
    diario es la red de respaldo por si el backend no se reinicio en meses.
    """
    logger.info("Verificando cronograma SUNAT vigente...")
    db = SessionLocal()
    try:
        resultado = asegurar_cronograma_vigente(db)
        logger.info(f"Cronograma SUNAT: {resultado}")
    except Exception:
        logger.exception("Fallo la verificacion del cronograma SUNAT")
    try:
        resultado_sire = asegurar_cronograma_sire_vigente(db)
        logger.info(f"Cronograma SIRE: {resultado_sire}")
    except Exception:
        logger.exception("Fallo la verificacion del cronograma SIRE")
    finally:
        db.close()


def job_generar_tareas_mes():
    """
    Modulo de Tareas/Agenda: red de respaldo diaria para generar_tareas_mes()
    (ver app/tareas.py). Crear o activar una obligacion ya la dispara sola
    para el mes actual (ver routers.tareas._generar_mes_actual_silencioso y
    routers.empresas._crear_obligaciones_por_defecto), pero esto cubre lo
    que ese disparo puntual no cubre: el cambio de mes (el 1 de cada mes,
    las obligaciones que ya existian necesitan su tarea del periodo nuevo)
    y cualquier caso raro donde el disparo puntual haya fallado. Corre para
    TODOS los tenants activos, una vez al dia -- idempotente, asi que en la
    inmensa mayoria de los dias no crea nada nuevo (ya esta al dia).
    """
    logger.info("Generando tareas del mes para todos los tenants...")
    db = SessionLocal()
    try:
        hoy = datetime.now(timezone.utc)
        tenants = db.query(Tenant).filter(Tenant.activo.is_(True)).all()
        total_creadas = 0
        for tenant in tenants:
            resultado = generar_tareas_mes(db, tenant.id, hoy.year, hoy.month)
            total_creadas += resultado["tareas_creadas"]
        logger.info(f"Tareas del mes: {total_creadas} nueva(s) en {len(tenants)} tenant(s).")
    except Exception:
        logger.exception("Fallo la generacion automatica de tareas del mes")
    finally:
        db.close()


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="UTC")

    # Punto 6: horario inicial de chequeo_1/chequeo_2 sale de ConfiguracionSistema
    # (con fallback a las variables de entorno CHEQUEO1_*/CHEQUEO2_* si la fila
    # todavia no existe) -- ver horarios_chequeo() en app.rate_limit.
    horarios_iniciales = horarios_chequeo()
    _horario_actual.update(horarios_iniciales)

    scheduler.add_job(
        lambda: job_chequeo("chequeo_1"),
        CronTrigger(hour=horarios_iniciales["chequeo1_hora"], minute=horarios_iniciales["chequeo1_minuto"]),
        id="chequeo_1",
    )
    scheduler.add_job(
        lambda: job_resumen("11:00 Peru"),
        CronTrigger(hour=RESUMEN1_HORA_UTC, minute=RESUMEN1_MINUTO_UTC),
        id="resumen_1",
    )
    scheduler.add_job(
        lambda: job_chequeo("chequeo_2"),
        CronTrigger(hour=horarios_iniciales["chequeo2_hora"], minute=horarios_iniciales["chequeo2_minuto"]),
        id="chequeo_2",
    )
    scheduler.add_job(
        lambda: job_resumen("19:30 Peru"),
        CronTrigger(hour=RESUMEN2_HORA_UTC, minute=RESUMEN2_MINUTO_UTC),
        id="resumen_2",
    )
    scheduler.add_job(
        job_canario,
        IntervalTrigger(minutes=CANARIO_INTERVALO_MIN),
        id="canario",
    )
    scheduler.add_job(
        lambda: job_recargar_horarios(scheduler),
        IntervalTrigger(minutes=RECARGA_HORARIOS_INTERVALO_MIN),
        id="recargar_horarios",
    )
    scheduler.add_job(
        job_cronograma,
        CronTrigger(hour=5, minute=0),
        id="cronograma",
    )
    scheduler.add_job(
        job_limpieza_diagnosticos,
        CronTrigger(hour=4, minute=30),
        id="limpieza_diagnosticos",
    )
    scheduler.add_job(
        job_generar_tareas_mes,
        CronTrigger(hour=5, minute=15),
        id="generar_tareas_mes",
    )
    logger.info(
        "Scheduler arrancado. Chequeos diarios a las "
        f"{horarios_iniciales['chequeo1_hora']:02d}:{horarios_iniciales['chequeo1_minuto']:02d} UTC y "
        f"{horarios_iniciales['chequeo2_hora']:02d}:{horarios_iniciales['chequeo2_minuto']:02d} UTC "
        "(editable sin redeploy en Panel maestro > horario de consulta masiva), "
        "con su resumen ~2h despues de cada uno (horario fijo, no editable). "
        f"Chequeo canario cada {CANARIO_INTERVALO_MIN} minutos. "
        f"Horario de chequeo recargado cada {RECARGA_HORARIOS_INTERVALO_MIN} minutos. "
        "Verificacion del cronograma SUNAT a las 05:00 UTC. "
        "Limpieza de datos de diagnostico a las 04:30 UTC. "
        "Generacion de tareas del mes (todos los tenants) a las 05:15 UTC. "
        "(para probar sin esperar, usa los endpoints /admin/chequeo-nocturno, "
        "/admin/enviar-resumenes, /admin/canario/ejecutar, /admin/limpieza-diagnosticos "
        "y POST /cronograma/sincronizar; para tareas, POST /tareas/generar)"
    )
    scheduler.start()
