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
    `docker restart`), el job queda "en_progreso" para siempre. Se encontro
    asi en produccion: 5 jobs "en_progreso" de hasta 6 dias de antiguedad.

    Update (29/09, escalando de 1 a varios workers en paralelo): la version
    anterior de esta funcion asumia "cualquier job en_progreso que vea al
    arrancar es huerfano, porque yo (este proceso) todavia no procese nada"
    -- eso es correcto con un solo worker, pero es un bug real con 2 o mas:
    si el Worker B arranca (o se reinicia por un deploy) mientras el Worker
    A esta genuinamente a mitad de una consulta, B encontraria el job de A
    "en_progreso" y lo marcaria como error de golpe, aunque A lo siga
    procesando bien. Por la misma razon, la version anterior tambien
    borraba ENTERO el semaforo de concurrencia (sunat:consultas_en_curso)
    al arrancar -- con varios workers, eso le borraba a A el cupo que tenia
    reservado de forma legitima.

    Ahora el criterio es por TIEMPO, no por "soy nuevo": un job solo se
    considera huerfano si lleva mas de LIMITE_HUERFANO en_progreso -- bien
    por encima del job_timeout="10m" que RQ le pone a todos estos jobs (ver
    el enqueue() en routers/consultas.py, empresas.py, ficha_ruc.py,
    reporte_tributario.py y scheduler_job.py), asi que ningun job
    legitimamente en curso puede superarlo por mas workers que haya
    arrancando o reiniciandose al mismo tiempo. Ya no hace falta tocar el
    semaforo global aca: desde el fix del 28/09 es un ZSET con vencimiento
    propio por cupo (ver adquirir_slot_global en app/rate_limit.py), que ya
    se autolimpia solo sin depender de que ningun worker arranque.

    De paso se suman FichaRucJob y ReporteTributarioJob a la limpieza --
    antes solo se cubria ConsultaJob, aunque los otros dos tipos de job
    pueden quedar huerfanos exactamente igual.
    """
    from datetime import datetime, timedelta, timezone
    from app.database import SessionLocal
    from app.models import ConsultaJob, FichaRucJob, ReporteTributarioJob

    LIMITE_HUERFANO = timedelta(minutes=15)
    corte = datetime.now(timezone.utc) - LIMITE_HUERFANO

    db = SessionLocal()
    try:
        total_huerfanos = 0
        for Modelo in (ConsultaJob, FichaRucJob, ReporteTributarioJob):
            huerfanos = (
                db.query(Modelo)
                .filter(Modelo.estado == "en_progreso", Modelo.iniciado_en < corte)
                .all()
            )
            for job in huerfanos:
                job.estado = "error"
                job.finalizado_en = datetime.now(timezone.utc)
                job.error = "Job huerfano: el worker que lo procesaba se reinicio o fallo antes de terminar (limpiado automaticamente)"
            total_huerfanos += len(huerfanos)
        if total_huerfanos:
            db.commit()
            logger.warning(f"Reconciliacion al arrancar: {total_huerfanos} job(s) huerfano(s) marcados como error.")
    finally:
        db.close()

    logger.info("Reconciliacion al arrancar completa.")


if __name__ == "__main__":
    _reconciliar_al_arrancar()
    logger.info("Worker RQ arrancando, escuchando la cola 'consultas_buzon'...")
    worker = Worker([cola_consultas], connection=redis_conn)
    # with_scheduler=True: necesario para que funcionen los enqueue_in() que
    # usa el chequeo nocturno (Fase 2) para espaciar las consultas de todas
    # las empresas en el tiempo, en vez de dispararlas todas de una.
    worker.work(with_scheduler=True)
