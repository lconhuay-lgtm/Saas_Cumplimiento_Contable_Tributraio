"""
API oficial del SIRE (Liquidacion en vivo, Etapa 1): token OAuth2 de SUNAT
y la consulta de periodos que sirve de "Probar conexion".

El cliente genera su client_id/client_secret en el Menu SOL ("Credenciales
de API SUNAT"); el usuario y la clave SOL son los mismos que ya guarda
CredencialSol. SUNAT pide el usuario como RUC + usuario SOL, todo junto.
Nada de esto usa Selenium ni ocupa la sesion SOL de la empresa.
"""
import logging

import requests

logger = logging.getLogger(__name__)

URL_TOKEN = "https://api-seguridad.sunat.gob.pe/v1/clientessol/{client_id}/oauth2/token/"
SCOPE_SIRE = "https://api-sire.sunat.gob.pe"
# Mismo endpoint que lee el modulo SIRE por la sesion web (adapter._URL_PERIODOS_SIRE):
# solo lista periodos si la empresa esta en el SIRE.
URL_PERIODOS_RVIE = "https://api-sire.sunat.gob.pe/v1/contribuyente/migeigv/libros/rvierce/padron/web/omisos/140000/periodos"
TIMEOUT_SEG = 20


class ErrorApiSire(Exception):
    """Falla con un mensaje ya listo para mostrar al usuario."""


def _detalle_sunat(respuesta: requests.Response) -> str:
    try:
        datos = respuesta.json()
    except ValueError:
        return respuesta.text[:200]
    if isinstance(datos, dict):
        return str(datos.get("error_description") or datos.get("msg") or datos.get("msj") or datos.get("error") or datos)[:200]
    return str(datos)[:200]


def obtener_token(client_id: str, client_secret: str, ruc: str, usuario_sol: str, clave_sol: str) -> str:
    try:
        r = requests.post(
            URL_TOKEN.format(client_id=client_id),
            data={
                "grant_type": "password",
                "scope": SCOPE_SIRE,
                "client_id": client_id,
                "client_secret": client_secret,
                "username": f"{ruc}{usuario_sol}",
                "password": clave_sol,
            },
            timeout=TIMEOUT_SEG,
        )
    except requests.RequestException as e:
        logger.warning(f"Token SIRE {ruc}: sin respuesta de SUNAT ({e})")
        raise ErrorApiSire("SUNAT no respondió. Intenta de nuevo en unos minutos.")

    if r.status_code == 200:
        token = (r.json() or {}).get("access_token")
        if token:
            return token
        raise ErrorApiSire("SUNAT respondió sin token. Intenta de nuevo en unos minutos.")

    detalle = _detalle_sunat(r)
    logger.warning(f"Token SIRE {ruc}: HTTP {r.status_code} {detalle}")
    texto = detalle.lower()
    if "client" in texto:
        raise ErrorApiSire("El ID o la clave de la API no son válidos. Revisa que estén bien copiados del Menú SOL.")
    if "grant" in texto or "usuario" in texto or "password" in texto or "clave" in texto:
        raise ErrorApiSire("SUNAT rechazó el usuario o la clave SOL guardados de la empresa.")
    if r.status_code >= 500:
        raise ErrorApiSire("SUNAT no respondió. Intenta de nuevo en unos minutos.")
    raise ErrorApiSire(f"SUNAT rechazó la conexión: {detalle}")


def probar_conexion(client_id: str, client_secret: str, ruc: str, usuario_sol: str, clave_sol: str) -> int:
    """Pide el token y lista los periodos del Registro de Ventas. Devuelve cuantos periodos hay."""
    token = obtener_token(client_id, client_secret, ruc, usuario_sol, clave_sol)
    try:
        r = requests.get(URL_PERIODOS_RVIE, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT_SEG)
    except requests.RequestException as e:
        logger.warning(f"Periodos SIRE {ruc}: sin respuesta ({e})")
        raise ErrorApiSire("La conexión funcionó, pero el SIRE no respondió. Intenta de nuevo en unos minutos.")
    if r.status_code != 200:
        detalle = _detalle_sunat(r)
        logger.warning(f"Periodos SIRE {ruc}: HTTP {r.status_code} {detalle}")
        raise ErrorApiSire(f"La conexión funcionó, pero el SIRE devolvió un error: {detalle}")
    datos = r.json()
    return sum(len(ejercicio.get("lisPeriodos") or []) for ejercicio in datos) if isinstance(datos, list) else 0
