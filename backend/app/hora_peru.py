"""
Hora de Peru para todo lo que depende del DIA o del MES (hoy, vencido, mes en
curso, "llego hoy", limites por dia). El servidor corre en UTC, 5 horas
adelante: sin esto, desde las 7 p.m. de Peru el sistema ya creia que era el
dia siguiente (tareas "vencidas" la noche anterior, tareas del mes siguiente
generadas el ultimo dia a la noche, etc.).

Convencion de las FECHAS de vencimiento (cronograma, tareas): se guardan como
medianoche UTC del dia del calendario -- una "etiqueta" de fecha, que el
frontend muestra con timeZone UTC. Por eso "ya vencio" se compara contra la
etiqueta de HOY en Peru (etiqueta_de_hoy), no contra el instante actual.
Los INSTANTES (descubierto_en, creado_en...) siguen en UTC real.
"""
from datetime import date, datetime, timedelta, timezone

# Peru no tiene horario de verano: UTC-5 todo el anio.
ZONA_PERU = timezone(timedelta(hours=-5), "PET")


def ahora_peru() -> datetime:
    return datetime.now(ZONA_PERU)


def hoy_peru() -> date:
    return ahora_peru().date()


def etiqueta_de_dia(dia: date) -> datetime:
    """El dia del calendario como se guardan las fechas de vencimiento (00:00 UTC de ese dia)."""
    return datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc)


def etiqueta_de_hoy() -> datetime:
    """Hoy en Peru, en el formato de las fechas de vencimiento: lo menor a esto ya vencio."""
    return etiqueta_de_dia(hoy_peru())


def inicio_de_hoy_peru() -> datetime:
    """El instante (en UTC) en que empezo hoy en Peru: para "mensajes de hoy", "reportes de hoy", etc."""
    hoy = hoy_peru()
    return datetime(hoy.year, hoy.month, hoy.day, tzinfo=ZONA_PERU).astimezone(timezone.utc)
