"""
API oficial del SIRE (Liquidacion en vivo): token OAuth2 de SUNAT, la
consulta de periodos que sirve de "Probar conexion" (Etapa 1) y la descarga
de la propuesta de ventas (RVIE) y compras (RCE) de un periodo (Bloque 1).

El cliente genera su client_id/client_secret en el Menu SOL ("Credenciales
de API SUNAT"); el usuario y la clave SOL son los mismos que ya guarda
CredencialSol. SUNAT pide el usuario como RUC + usuario SOL, todo junto.
Nada de esto usa Selenium ni ocupa la sesion SOL de la empresa.
"""
import io
import logging
import time
import unicodedata
import zipfile
from datetime import datetime

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


# --- Propuesta del periodo (Bloque 1) ---
# Probado con BASCAT el 28/10/2026: la propuesta del mes en curso existe
# durante el mes. Se pide por ticket, el archivo esta listo en ~10 s y llega
# en un zip con un txt separado por "|" con encabezado.
URL_LIBROS = "https://api-sire.sunat.gob.pe/v1/contribuyente/migeigv/libros"
COD_LIBRO = {"RVIE": "140000", "RCE": "080000"}
ESPERA_TICKET_SEG = 10
INTENTOS_TICKET = 18


def _get(token: str, url: str, **params) -> requests.Response:
    try:
        return requests.get(
            url, params=params or None, timeout=60,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
    except requests.RequestException as e:
        raise ErrorApiSire(f"El SIRE no respondió ({e.__class__.__name__}). Se reintentará en la próxima lectura.")


def _exigir_200(r: requests.Response, que: str) -> None:
    if r.status_code == 429:
        raise ErrorApiSire(f"El SIRE pidió esperar antes de {que} (demasiados pedidos seguidos).")
    if r.status_code != 200:
        raise ErrorApiSire(f"El SIRE devolvió un error al {que}: HTTP {r.status_code} {_detalle_sunat(r)}")


def pedir_propuesta(token: str, libro: str, periodo: str) -> str:
    """Pide el archivo de la propuesta (periodo "AAAAMM") y devuelve el numero de ticket."""
    if libro == "RVIE":
        r = _get(token, f"{URL_LIBROS}/rvie/propuesta/web/propuesta/{periodo}/exportapropuesta", codTipoArchivo="0")
    else:
        r = _get(
            token, f"{URL_LIBROS}/rce/propuesta/web/propuesta/{periodo}/exportacioncomprobantepropuesta",
            codTipoArchivo="0", codOrigenEnvio="2",
        )
    _exigir_200(r, f"pedir la propuesta {libro} {periodo}")
    ticket = (r.json() or {}).get("numTicket")
    if not ticket:
        raise ErrorApiSire(f"El SIRE no devolvió ticket para la propuesta {libro} {periodo}.")
    return str(ticket)


def descargar_ticket(token: str, libro: str, periodo: str, ticket: str) -> bytes:
    """Espera a que el ticket termine y baja su archivo."""
    for _ in range(INTENTOS_TICKET):
        time.sleep(ESPERA_TICKET_SEG)
        r = _get(
            token, f"{URL_LIBROS}/rvierce/gestionprocesosmasivos/web/masivo/consultaestadotickets",
            perIni=periodo, perFin=periodo, page="1", perPage="20", numTicket=ticket,
        )
        _exigir_200(r, f"consultar el ticket {ticket}")
        registros = (r.json() or {}).get("registros") or []
        reg = registros[0] if registros else {}
        if "error" in str(reg.get("desEstadoProceso") or "").lower():
            raise ErrorApiSire(f"El SIRE no pudo generar la propuesta {libro} {periodo}: {reg.get('desEstadoProceso')}")
        archivos = reg.get("archivoReporte") or []
        if not archivos:
            continue
        a = archivos[0]
        d = _get(
            token, f"{URL_LIBROS}/rvierce/gestionprocesosmasivos/web/masivo/archivoreporte",
            nomArchivoReporte=a.get("nomArchivoReporte"),
            # SUNAT escribe "Achivo" en este campo.
            codTipoArchivoReporte=a.get("codTipoAchivoReporte") or a.get("codTipoArchivoReporte"),
            codLibro=COD_LIBRO[libro], perTributario=periodo, codProceso=reg.get("codProceso"), numTicket=ticket,
        )
        _exigir_200(d, f"descargar la propuesta {libro} {periodo}")
        return d.content
    raise ErrorApiSire(f"El SIRE no terminó de generar la propuesta {libro} {periodo} en 3 minutos.")


def _clave_columna(nombre: str) -> str:
    """'Apellidos Nombres/ Razón  Social' -> 'apellidos nombres/ razon social' (sin BOM, tildes ni espacios dobles)."""
    sin_tildes = unicodedata.normalize("NFKD", nombre.replace("﻿", "")).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


def leer_archivo_propuesta(contenido: bytes) -> list[dict]:
    """Filas del txt de la propuesta (dentro del zip), como {columna normalizada: valor}."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(contenido))
        texto = zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        texto = contenido.decode("utf-8", errors="replace")
    lineas = [linea for linea in texto.splitlines() if linea.strip()]
    if not lineas:
        return []
    columnas = [_clave_columna(c) for c in lineas[0].split("|")]
    return [dict(zip(columnas, (v.strip() for v in linea.split("|")))) for linea in lineas[1:]]


def _num(valor) -> float:
    try:
        return round(float(str(valor or "0").replace(",", "")), 2)
    except ValueError:
        return 0.0


def _fecha(valor) -> str | None:
    try:
        return datetime.strptime(str(valor or "").strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def normalizar_comprobante(libro: str, fila: dict, periodo: str) -> dict:
    """
    Una fila de la propuesta con los campos de LiquidacionComprobante.
    periodo: "AAAA-MM" pedido (se usa si la fila no trae el suyo).
    """
    g = fila.get
    tipo, serie, numero = g("tipo cp/doc.", ""), g("serie del cdp", ""), g("nro cp o doc. nro inicial (rango)", "")
    doc = g("nro doc identidad", "")
    per = g("periodo", "")
    comun = {
        "car_sunat": g("car sunat", "") or f"{tipo}-{serie}-{numero}-{doc}",
        "periodo": f"{per[:4]}-{per[4:6]}" if len(per) >= 6 and per[:6].isdigit() else periodo,
        "fecha_emision": _fecha(g("fecha de emision")),
        "tipo_comprobante": tipo,
        "serie": serie,
        "numero": numero,
        "doc_contraparte": doc,
        "nombre_contraparte": g("apellidos nombres/ razon social", ""),
        "total": _num(g("total cp")),
        "moneda": g("moneda", "") or "PEN",
        "datos": fila,
    }
    if libro == "RVIE":
        return {
            **comun,
            "base_gravada": _num(g("bi gravada")),
            "igv": _num(g("igv / ipm")),
            "descuento_base": _num(g("dscto bi")),
            "descuento_igv": _num(g("dscto igv / ipm")),
            "base_dgng": 0.0,
            "igv_dgng": 0.0,
            "no_gravado": round(_num(g("mto exonerado")) + _num(g("mto inafecto")), 2),
            "exportacion": _num(g("valor facturado exportacion")),
            "detraccion": "",
            "dam": "",
        }
    return {
        **comun,
        "base_gravada": _num(g("bi gravado dg")),
        "igv": _num(g("igv / ipm dg")),
        "descuento_base": 0.0,
        "descuento_igv": 0.0,
        "base_dgng": _num(g("bi gravado dgng")),
        "igv_dgng": _num(g("igv / ipm dgng")),
        "no_gravado": _num(g("valor adq. ng")),
        "exportacion": 0.0,
        "detraccion": g("detraccion", ""),
        "dam": g("cod. dam o dsi", ""),
    }


def descargar_propuesta(token: str, libro: str, periodo: str) -> list[dict]:
    """Comprobantes de la propuesta del periodo ("AAAA-MM"), ya normalizados."""
    aaaamm = periodo.replace("-", "")
    ticket = pedir_propuesta(token, libro, aaaamm)
    filas = leer_archivo_propuesta(descargar_ticket(token, libro, aaaamm, ticket))
    return [normalizar_comprobante(libro, f, periodo) for f in filas]
