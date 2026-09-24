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

if __name__ == "__main__":
    logger.info("Worker RQ arrancando, escuchando la cola 'consultas_buzon'...")
    worker = Worker([cola_consultas], connection=redis_conn)
    # with_scheduler=True: necesario para que funcionen los enqueue_in() que
    # usa el chequeo nocturno (Fase 2) para espaciar las consultas de todas
    # las empresas en el tiempo, en vez de dispararlas todas de una.
    worker.work(with_scheduler=True)
