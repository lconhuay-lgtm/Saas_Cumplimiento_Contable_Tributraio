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

Fase 5 (panel maestro): estos numeros -- y el espaciado entre consultas de
una tanda + el limite de mensajes por consulta -- ya no son fijos por
variable de entorno, se leen de ConfiguracionSistema (fila unica, ver
models.py) para que el equipo de la plataforma los pueda cambiar desde el
tablero (routers/admin.py, solo staff) sin redeploy. Las variables de
entorno de siempre quedan como default de arranque, por si esa fila
todavia no existe (instalacion nueva) o la base no responde -- un fallo
leyendo la configuracion NUNCA debe bloquear una consulta real.
"""
import os
import time
import logging

from app.queue_conn import redis_conn
from app.database import SessionLocal
from app.models import ConfiguracionSistema

logger = logging.getLogger("app.rate_limit")

_MAX_CONCURRENTES_DEFAULT = int(os.environ.get("SUNAT_MAX_CONSULTAS_CONCURRENTES", 3))
_SEGUNDOS_ENTRE_CONSULTAS_RUC_DEFAULT = int(os.environ.get("SUNAT_SEGUNDOS_ENTRE_CONSULTAS_MISMO_RUC", 60))
_ESPACIADO_CONSULTAS_SEG_DEFAULT = 45
_LIMITE_MENSAJES_POR_CONSULTA_DEFAULT = 20

# Punto 6 (horario configurable de chequeo automatico): mismos defaults que
# siempre tenia scheduler_entry.py -- se usan solo si la fila "global"
# todavia no existe o la base no responde, ver horarios_chequeo() abajo.
_CHEQUEO1_HORA_UTC_DEFAULT = int(os.environ.get("CHEQUEO1_HORA_UTC", "16"))
_CHEQUEO1_MINUTO_UTC_DEFAULT = int(os.environ.get("CHEQUEO1_MINUTO_UTC", "0"))
_CHEQUEO2_HORA_UTC_DEFAULT = int(os.environ.get("CHEQUEO2_HORA_UTC", "0"))
_CHEQUEO2_MINUTO_UTC_DEFAULT = int(os.environ.get("CHEQUEO2_MINUTO_UTC", "30"))

_CLAVE_CONCURRENCIA = "sunat:consultas_en_curso"


class LimiteExcedido(Exception):
    """Se intento consultar SUNAT mas seguido o en mas paralelo de lo permitido."""


def _configuracion_actual() -> ConfiguracionSistema | None:
    """
    Sesion propia y de corta duracion (no reusa la del llamador): a este
    modulo lo importan tanto endpoints (con su sesion de request) como el
    worker/scheduler (sin sesion de FastAPI de por medio) -- mas simple una
    sesion aislada aca que threadear `db` a traves de cada funcion de este
    modulo. Se llama como mucho una o dos veces por chequeo (nunca dentro
    de un loop de reintentos, ver adquirir_slot_global), asi que el costo
    extra es despreciable. Si la base no responde, se traga el error y
    devuelve None -- el llamador cae al default de variable de entorno en
    vez de tumbar una consulta real por un problema de configuracion.
    """
    try:
        db = SessionLocal()
        try:
            return db.query(ConfiguracionSistema).filter(ConfiguracionSistema.id == "global").first()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"No se pudo leer la configuracion del sistema, uso los valores por defecto: {e}")
        return None


def obtener_o_crear_configuracion(db) -> ConfiguracionSistema:
    """
    Get-or-create de la fila unica -- para el panel maestro (GET/PUT
    /admin/configuracion, ver routers/admin.py), que usa la sesion del
    propio request. A diferencia de _configuracion_actual() de arriba, aca
    SI se deja que un fallo real de base de datos se propague: el panel
    necesita saber si de verdad no pudo leer/guardar.
    """
    config = db.query(ConfiguracionSistema).filter(ConfiguracionSistema.id == "global").first()
    if config is None:
        config = ConfiguracionSistema(id="global")
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def max_concurrentes() -> int:
    config = _configuracion_actual()
    return config.concurrencia_maxima if config else _MAX_CONCURRENTES_DEFAULT


def segundos_entre_consultas_ruc() -> int:
    config = _configuracion_actual()
    return config.segundos_entre_consultas_mismo_ruc if config else _SEGUNDOS_ENTRE_CONSULTAS_RUC_DEFAULT


def espaciado_consultas_seg() -> int:
    """Espaciado entre cada empresa de una tanda -- chequeo nocturno, 'Consultar todas', importacion masiva."""
    config = _configuracion_actual()
    return config.espaciado_seg_entre_consultas if config else _ESPACIADO_CONSULTAS_SEG_DEFAULT


def limite_mensajes_por_consulta() -> int:
    config = _configuracion_actual()
    return config.limite_mensajes_por_consulta if config else _LIMITE_MENSAJES_POR_CONSULTA_DEFAULT


def horarios_chequeo() -> dict:
    """
    Punto 6: hora UTC de los 2 chequeos automaticos diarios (consulta masiva
    de todas las empresas activas), leida de ConfiguracionSistema en vez de
    fija por variable de entorno. La llama scheduler_entry.py al arrancar y
    despues cada pocos minutos, para reprogramar el cron job en caliente si
    alguien la cambio desde el panel maestro -- sin reiniciar el contenedor.
    """
    config = _configuracion_actual()
    if config is None:
        return {
            "chequeo1_hora": _CHEQUEO1_HORA_UTC_DEFAULT,
            "chequeo1_minuto": _CHEQUEO1_MINUTO_UTC_DEFAULT,
            "chequeo2_hora": _CHEQUEO2_HORA_UTC_DEFAULT,
            "chequeo2_minuto": _CHEQUEO2_MINUTO_UTC_DEFAULT,
        }
    return {
        "chequeo1_hora": config.chequeo1_hora,
        "chequeo1_minuto": config.chequeo1_minuto,
        "chequeo2_hora": config.chequeo2_hora,
        "chequeo2_minuto": config.chequeo2_minuto,
    }


def verificar_limite_ruc(ruc: str) -> None:
    """
    Lanza LimiteExcedido si ESTE RUC puntual ya se consulto hace menos de
    segundos_entre_consultas_ruc(). SET NX EX es atomico: dos requests
    simultaneas para el mismo RUC no pueden pasar las dos a la vez.

    La clave de Redis incluye el RUC (sunat:ultima_consulta:{ruc}), asi que
    el limite es POR EMPRESA -- consultar el RUC 123... no afecta para nada
    al RUC 456.... Se confirmo esto releyendo el codigo a fondo (no se
    encontro ningun bug de scope compartido) despues de un reporte de que
    "parecia" bloquear entre empresas distintas; el mensaje de error de
    abajo ahora incluye el RUC exacto que esta bloqueado, para que quede
    imposible confundirlo con un limite global la proxima vez que pase.
    """
    segundos = segundos_entre_consultas_ruc()
    clave = f"sunat:ultima_consulta:{ruc}"
    fue_seteado = redis_conn.set(clave, "1", nx=True, ex=segundos)
    if not fue_seteado:
        ttl = redis_conn.ttl(clave)
        espera = ttl if ttl and ttl > 0 else segundos
        raise LimiteExcedido(
            f"El RUC {ruc} se consulto hace poco. Espera {espera} segundos antes de volver a "
            "intentar con ESTE MISMO RUC (otras empresas no se ven afectadas)."
        )


def adquirir_slot_global(espera_maxima_seg: int = 240, intervalo_seg: int = 3) -> None:
    """
    Bloquea (con timeout) hasta que haya cupo para una sesion mas de Selenium
    contra SUNAT, respetando max_concurrentes() en todo el sistema. Se usa
    dentro del worker, antes de abrir el navegador.
    """
    limite = max_concurrentes()
    inicio = time.time()
    while True:
        actual = redis_conn.incr(_CLAVE_CONCURRENCIA)
        if actual <= limite:
            return
        redis_conn.decr(_CLAVE_CONCURRENCIA)
        if time.time() - inicio > espera_maxima_seg:
            raise LimiteExcedido(
                f"No hay cupo para consultar SUNAT ahora mismo (maximo {limite} en paralelo). "
                "Intenta de nuevo en unos minutos."
            )
        logger.info(f"Esperando cupo para consultar SUNAT ({actual}/{limite} ocupados)...")
        time.sleep(intervalo_seg)


def liberar_slot_global() -> None:
    redis_conn.decr(_CLAVE_CONCURRENCIA)
