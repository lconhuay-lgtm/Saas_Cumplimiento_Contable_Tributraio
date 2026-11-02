"""
Jobs "huerfanos": si el worker que procesaba un job muere a mitad (crash,
OOM, un despliegue que reinicia los workers), el job queda "en_progreso" para
siempre, y en Cumplimiento eso bloquea las lecturas siguientes de esa empresa
(encolar_lecturas salta las que tienen una en curso).

El criterio es por TIEMPO (ver el historial en worker_entry._reconciliar_al_arrancar):
un job es huerfano si lleva en_progreso mas que el job_timeout con que se
encola mas un margen, porque pasado ese tiempo RQ ya lo habria cortado. Asi es
seguro con varios workers. Corre al arrancar cada worker y, cada 15 minutos,
desde el scheduler: un job cortado por un despliegue todavia es "nuevo" cuando
los workers arrancan, y sin la pasada periodica no se limpiaba nunca (QORI
HOME, detracciones, 02/11/2026).
"""
import logging
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import (
    ConsultaDeclaracionesJob, ConsultaDetraccionesJob, ConsultaDeudasJob, ConsultaJob, ConsultaSireJob, FichaRucJob,
    LiquidacionLectura, ReporteTributarioJob,
)

logger = logging.getLogger("app.huerfanos")

# Margen sobre el job_timeout mas largo de cada tipo: 10m las consultas
# comunes, 40m la carga inicial de detracciones y 90m el trabajo de lecturas
# de la Liquidacion en vivo (una fila por fuente, todas dentro del mismo job).
LIMITES_HUERFANO = {
    ConsultaJob: timedelta(minutes=15),
    FichaRucJob: timedelta(minutes=15),
    ReporteTributarioJob: timedelta(minutes=15),
    ConsultaSireJob: timedelta(minutes=15),
    ConsultaDeudasJob: timedelta(minutes=15),
    ConsultaDeclaracionesJob: timedelta(minutes=15),
    ConsultaDetraccionesJob: timedelta(minutes=45),
    LiquidacionLectura: timedelta(minutes=95),
}

MENSAJE_HUERFANO = "Job huerfano: el worker que lo procesaba se reinicio o fallo antes de terminar (limpiado automaticamente)"


def marcar_jobs_huerfanos() -> int:
    """Marca como error los jobs en_progreso que superaron su limite. Devuelve cuantos."""
    ahora = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        total = 0
        for Modelo, limite in LIMITES_HUERFANO.items():
            huerfanos = db.query(Modelo).filter(Modelo.estado == "en_progreso", Modelo.iniciado_en < ahora - limite).all()
            for job in huerfanos:
                job.estado = "error"
                job.etapa = None
                job.finalizado_en = ahora
                job.error = MENSAJE_HUERFANO
            total += len(huerfanos)
        if total:
            db.commit()
            logger.warning(f"{total} job(s) huerfano(s) marcados como error.")
        return total
    finally:
        db.close()
