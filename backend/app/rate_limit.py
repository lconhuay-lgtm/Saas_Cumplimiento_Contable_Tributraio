"""
Limites para no golpear a SUNAT como si fueramos un ataque:

1. Por RUC: no permitir dos consultas de la misma empresa demasiado seguido
   (se revisa al ENCOLAR, en la API -- devuelve 429 de inmediato en vez de
   encolar un trabajo que de todas formas se va a saltar).
2. Global: limitar cuantas sesiones de Selenium contra SUNAT corren al mismo
   tiempo en todo el sistema, sin importar cuantos workers haya (se revisa
   al EJECUTAR, dentro del worker, como un semaforo).

Ambos usan Redis para que el limite se respete entre todos los procesos
(backend + los workers que hagan falta), no solo dentro de uno.
"""
import os
import time
import logging

from app.queue_conn import redis_conn

logger = logging.getLogger("app.rate_limit")

MAX_CONCURRENTES = int(os.environ.get("SUNAT_MAX_CONSULTAS_CONCURRENTES", 3))
SEGUNDOS_ENTRE_CONSULTAS_RUC = int(os.environ.get("SUNAT_SEGUNDOS_ENTRE_CONSULTAS_MISMO_RUC", 60))

_CLAVE_CONCURRENCIA = "sunat:consultas_en_curso"


class LimiteExcedido(Exception):
    """Se intento consultar SUNAT mas seguido o en mas paralelo de lo permitido."""


def verificar_limite_ruc(ruc: str) -> None:
    """
    Lanza LimiteExcedido si ESTE RUC puntual ya se consulto hace menos de
    SEGUNDOS_ENTRE_CONSULTAS_RUC. SET NX EX es atomico: dos requests
    simultaneas para el mismo RUC no pueden pasar las dos a la vez.

    La clave de Redis incluye el RUC (sunat:ultima_consulta:{ruc}), asi que
    el limite es POR EMPRESA -- consultar el RUC 123... no afecta para nada
    al RUC 456.... Se confirmo esto releyendo el codigo a fondo (no se
    encontro ningun bug de scope compartido) despues de un reporte de que
    "parecia" bloquear entre empresas distintas; el mensaje de error de
    abajo ahora incluye el RUC exacto que esta bloqueado, para que quede
    imposible confundirlo con un limite global la proxima vez que pase.
    """
    clave = f"sunat:ultima_consulta:{ruc}"
    fue_seteado = redis_conn.set(clave, "1", nx=True, ex=SEGUNDOS_ENTRE_CONSULTAS_RUC)
    if not fue_seteado:
        ttl = redis_conn.ttl(clave)
        espera = ttl if ttl and ttl > 0 else SEGUNDOS_ENTRE_CONSULTAS_RUC
        raise LimiteExcedido(
            f"El RUC {ruc} se consulto hace poco. Espera {espera} segundos antes de volver a "
            "intentar con ESTE MISMO RUC (otras empresas no se ven afectadas)."
        )


def adquirir_slot_global(espera_maxima_seg: int = 240, intervalo_seg: int = 3) -> None:
    """
    Bloquea (con timeout) hasta que haya cupo para una sesion mas de Selenium
    contra SUNAT, respetando MAX_CONCURRENTES en todo el sistema. Se usa
    dentro del worker, antes de abrir el navegador.
    """
    inicio = time.time()
    while True:
        actual = redis_conn.incr(_CLAVE_CONCURRENCIA)
        if actual <= MAX_CONCURRENTES:
            return
        redis_conn.decr(_CLAVE_CONCURRENCIA)
        if time.time() - inicio > espera_maxima_seg:
            raise LimiteExcedido(
                f"No hay cupo para consultar SUNAT ahora mismo (maximo {MAX_CONCURRENTES} en paralelo). "
                "Intenta de nuevo en unos minutos."
            )
        logger.info(f"Esperando cupo para consultar SUNAT ({actual}/{MAX_CONCURRENTES} ocupados)...")
        time.sleep(intervalo_seg)


def liberar_slot_global() -> None:
    redis_conn.decr(_CLAVE_CONCURRENCIA)
