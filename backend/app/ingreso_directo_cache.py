"""
Cache de un "ticket" de ingreso directo (velocidad, Fase 3.5) -- ver
routers/empresas.py::ingreso_directo para el flujo completo.

La idea clave: el descubrimiento de un ticket fresco (accion_url / state /
originalUrl / lang) es EXACTAMENTE el mismo sin importar que empresa vaya a
usarlo despues -- no depende de ningun RUC ni credencial, solo de "cuando
SUNAT genero ese state" (ver preparar_ingreso_directo en adapter.py). Por
eso un solo ticket cacheado en Redis puede servir para CUALQUIER empresa
que haga clic en "Ir a SUNAT" mientras siga fresco, evitando abrir un
Chrome/Selenium nuevo (15-30s) en cada clic.

DEFAULT_MAX_EDAD_SEG confirmado EMPIRICAMENTE con
diagnosticar_frescura_ingreso_directo.py (corrida real, 18/09): SUNAT
acepto el ticket sin ningun problema en las rondas de 0/20/40/60/90
segundos de antiguedad -- ninguna fallo. La ronda de 120s no llego a
confirmarse en esa corrida (se corto antes de terminar), asi que por ahora
el numero se deja en el ultimo valor CONFIRMADO (90s) y no en el mayor
probado. Si una corrida futura confirma 120s o mas, subir este numero es
el UNICO cambio que hace falta para aprovechar mas "cache hits" sin tocar
nada mas de la logica.

Si no hay nada cacheado o esta viejo, el llamador (routers/empresas.py)
simplemente hace el descubrimiento en vivo -- EXACTAMENTE el mismo
comportamiento que existia antes de este cache. Este modulo nunca puede
hacer que el flujo salga peor de lo que ya estaba, solo mejor cuando hay
un ticket fresco esperando.
"""
import json
import logging
import time

from app.queue_conn import redis_conn

logger = logging.getLogger("app.ingreso_directo_cache")

_CLAVE_TICKET = "ingreso_directo:ticket"
# Techo duro en Redis (EX) -- una red de seguridad ademas del chequeo de
# edad de abajo, para que un ticket nunca quede dando vueltas indefinidamente
# en el cache aunque algo en la logica de arriba fallara.
_TTL_REDIS_SEG = 180
DEFAULT_MAX_EDAD_SEG = 90


def guardar_ticket(resultado: dict) -> None:
    """Guarda un ticket recien descubierto (el dict que devuelve preparar_ingreso_directo, con ok=True) junto con cuando se genero."""
    payload = {**resultado, "descubierto_en": time.time()}
    redis_conn.set(_CLAVE_TICKET, json.dumps(payload), ex=_TTL_REDIS_SEG)


def obtener_ticket_fresco(max_edad_segundos: int = DEFAULT_MAX_EDAD_SEG) -> dict | None:
    """
    Devuelve el ticket cacheado SOLO si sigue lo bastante fresco, y lo
    borra de una vez del cache (de un solo uso -- asi dos clics casi
    simultaneos de usuarios distintos no terminan reusando el mismo
    ticket). Devuelve None si no habia nada cacheado o ya esta viejo -- en
    ese caso el llamador hace el descubrimiento en vivo como siempre.
    """
    crudo = redis_conn.get(_CLAVE_TICKET)
    if not crudo:
        return None
    redis_conn.delete(_CLAVE_TICKET)  # de un solo uso, se aproveche o no esta vez
    try:
        ticket = json.loads(crudo)
    except (TypeError, ValueError):
        return None
    edad = time.time() - ticket.get("descubierto_en", 0)
    if edad > max_edad_segundos:
        logger.info(f"Ticket de ingreso directo cacheado descartado por viejo ({edad:.1f}s)")
        return None
    return ticket


def prewarm_ingreso_directo_job() -> None:
    """
    Job de RQ (corre en el worker, que ya tiene su propia pantalla virtual
    arrancada por worker_entry.py -- no hace falta arrancar una aca):
    hace UN descubrimiento (el mismo preparar_ingreso_directo de siempre,
    sin ruc especifico porque el ticket no depende de la empresa) y lo deja
    listo en el cache. Se encola cuando alguien abre la lista de empresas
    (ver POST /empresas/ingreso-directo/prewarm) -- asi el costo de abrir
    Chrome solo se paga cuando de verdad hay alguien mirando la pantalla,
    no en un loop de fondo permanente.
    """
    from adapter import preparar_ingreso_directo
    from app.rate_limit import adquirir_slot_global, liberar_slot_global

    adquirir_slot_global()
    try:
        resultado = preparar_ingreso_directo()
    finally:
        liberar_slot_global()

    if resultado.get("ok"):
        guardar_ticket(resultado)
        logger.info("Ticket de ingreso directo pre-calentado y cacheado.")
    else:
        logger.warning(
            "Prewarm de ingreso directo fallo (no es grave, el proximo clic hace el "
            f"descubrimiento en vivo como siempre): {resultado.get('error')}"
        )
