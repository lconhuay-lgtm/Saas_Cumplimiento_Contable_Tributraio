#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Punto de entrada del worker.

Dos cosas que hace este archivo, en vez de usar `rq worker` directo:

1. Llama a config.setup_logging() del motor -- `rq worker` nunca la llama,
   asi que todos los logger.info(...) de web_navigation.py (cada paso:
   "Primer clic exitoso", "Ingresando credenciales", etc.) quedaban
   silenciados, solo se veian los WARNING/ERROR sin contexto.

2. Arranca una pantalla virtual (Xvfb) DESDE PYTHON con pyvirtualdisplay, en
   vez de envolver el proceso con el comando `xvfb-run` (que se quedo
   colgado en silencio sin arrancar nada -- una hora corriendo sin una sola
   linea de log). Haciendolo aqui, cualquier error al arrancar Xvfb se ve
   con claridad en los logs, y sabemos con certeza que la pantalla esta
   lista ANTES de empezar a atender trabajos.

Por que hace falta una pantalla en absoluto: e-menu.sunat.gob.pe (el login
real de SUNAT) corta la conexion cuando detecta Chrome en modo headless.
Con Xvfb, Chrome corre "visible" (sin ninguna senal de headless) dentro de
una pantalla que nunca se le muestra a nadie.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as core_config  # config.py de core_scraper (ya esta en PYTHONPATH)
core_config.setup_logging()

import logging
logger = logging.getLogger("worker_entry")

from pyvirtualdisplay import Display

logger.info("Arrancando pantalla virtual (Xvfb) para que Chrome no corra en modo headless...")
display = Display(visible=False, size=(1600, 1000))
display.start()
logger.info(f"Pantalla virtual lista en DISPLAY={os.environ.get('DISPLAY')}")

from rq import Worker
from app.queue_conn import redis_conn, cola_consultas


def _reconciliar_al_arrancar():
    """
    Fix (hallazgo real, 24/09 -- diagnosticando por que "Ir a SUNAT" no
    cargaba): si un worker anterior murio a mitad de un job (crash, OOM,
    `docker restart`), el job queda "en_progreso" para siempre Y el cupo
    que ocupaba en el semaforo global (sunat:consultas_en_curso, ver
    app/rate_limit.py) nunca se libera -- adquirir_slot_global() nunca
    vuelve a ver ese cupo libre, sin importar cuanto tiempo pase, porque
    nadie ejecuta el liberar_slot_global() que le correspondia. Se
    encontro asi en produccion: 5 jobs "en_progreso" de hasta 6 dias de
    antiguedad, contador en 3/3 sin un solo Chrome corriendo.

    Al arrancar un worker fresco, cualquier job que siga "en_progreso" es
    por definicion huerfano -- este proceso todavia no proceso nada.

    Update (28/09): rate_limit.py paso de un contador simple (INCR/DECR) a
    un ZSET con vencimiento por cupo (cada cupo se autolimpia solo aunque
    nadie reinicie nada -- ver el docstring de adquirir_slot_global), asi
    que esta reconciliacion ya no es la UNICA red de seguridad, pero se
    deja igual: sigue sirviendo para arrancar siempre con el semaforo en
    cero apenas el worker es nuevo, sin esperar a que venzan cupos viejos.
    Se borra la clave entera en vez de "setearla a 0" porque ahora es un
    ZSET, no un contador.
    """
    from datetime import datetime, timezone
    from app.database import SessionLocal
    from app.models import ConsultaJob
    from app.rate_limit import _CLAVE_CONCURRENCIA

    db = SessionLocal()
    try:
        huerfanos = db.query(ConsultaJob).filter(ConsultaJob.estado == "en_progreso").all()
        for job in huerfanos:
            job.estado = "error"
            job.finalizado_en = datetime.now(timezone.utc)
            job.error = "Job huerfano: el worker anterior se reinicio o fallo antes de terminar (limpiado automaticamente al arrancar)"
        if huerfanos:
            db.commit()
            logger.warning(f"Reconciliacion al arrancar: {len(huerfanos)} job(s) huerfano(s) marcados como error.")
    finally:
        db.close()

    redis_conn.delete(_CLAVE_CONCURRENCIA)
    logger.info("Reconciliacion al arrancar: semaforo de concurrencia SUNAT reseteado a 0.")


if __name__ == "__main__":
    _reconciliar_al_arrancar()
    logger.info("Worker RQ arrancando, escuchando la cola 'consultas_buzon'...")
    worker = Worker([cola_consultas], connection=redis_conn)
    # with_scheduler=True: necesario para que funcionen los enqueue_in() que
    # usa el chequeo nocturno (Fase 2) para espaciar las consultas de todas
    # las empresas en el tiempo, en vez de dispararlas todas de una.
    worker.work(with_scheduler=True)
