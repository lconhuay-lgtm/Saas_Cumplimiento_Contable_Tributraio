"""
Percepciones de IGV en importaciones, desde la consulta PUBLICA de
Liquidaciones de Cobranza de Aduanas (aduanet.gob.pe, sin clave SOL ni
captcha). Liquidacion en vivo, Bloque 1.

Se listan las LC canceladas del RUC como "Particular" (rlcoddes=9999) por
fecha de liquidacion, un mes por consulta (asi casi nunca hay segunda
pagina), y se abre el detalle de cada una: las de percepcion son "Tipo L/C:
0038 PERCEPCION IGV" con el concepto 0096. La cuenta de control de SUNAT las
imputa por fecha de liquidacion (CKM 09/2026: 1,768 + 1,005 = 2,773).
Probado con CKM y BASCAT el 27-28/10/2026.
"""
import html as html_lib
import logging
import re
import time
from datetime import date, datetime, timedelta

import requests

logger = logging.getLogger(__name__)

BASE = "http://www.aduanet.gob.pe"
URL_INICIO = f"{BASE}/cl-ad-itconsultalc/LiquidaConsultaListado.jsp"
URL_LISTADO = f"{BASE}/cl-ad-itconsultalc/clcS01Alias"
URL_DETALLE = f"{BASE}/servlet/SGRdetLC"
# Asi figura SUNAT como agente de las percepciones de importacion en la cuenta de control.
RUC_SUNAT_ADUANAS = "20131312955"
TIPO_PERCEPCION = "0038"
CONCEPTO_PERCEPCION = "0096"
PAUSA_SEG = 1.5
MAX_PAGINAS = 10


class ErrorAduanas(Exception):
    """Falla con un mensaje ya listo para mostrar al usuario."""


def _texto(fragmento: str) -> str:
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", fragmento)).replace("\xa0", " ").split())


def _fecha(ddmmaaaa: str) -> str | None:
    try:
        return datetime.strptime(ddmmaaaa.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def _monto(texto: str) -> float:
    try:
        return round(float(texto.replace(",", "")), 2)
    except ValueError:
        return 0.0


def meses(desde: date, hasta: date) -> list[tuple[date, date]]:
    """[desde, hasta] partido por mes calendario."""
    tramos = []
    ini = desde
    while ini <= hasta:
        siguiente = (ini.replace(day=1) + timedelta(days=32)).replace(day=1)
        tramos.append((ini, min(siguiente - timedelta(days=1), hasta)))
        ini = siguiente
    return tramos


def extraer_listado(pagina: str) -> tuple[list[dict], int | None]:
    """
    Filas "Adu-Ano-Nro LC | Fecha Liquid. | Fecha Notif. | Ultimo dia pago |
    Monto soles | Monto dolares | Origen | Fecha Cancel." con el enlace al
    detalle, y el total que dice "1 a 14 de 14" (None si no lo dice).
    """
    filas = []
    for fila in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", pagina):
        celdas = [_texto(c) for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", fila)]
        enlace = re.search(r"SGRdetLC\?([^\"'>]+)", fila)
        if len(celdas) >= 8 and re.fullmatch(r"\d{3}-\d{2}-\d+", celdas[0]) and enlace:
            filas.append({
                "lc": celdas[0],
                "fecha_liquidacion": _fecha(celdas[1]),
                "fecha_cancelacion": _fecha(celdas[7]),
                "origen": celdas[6],
                "consulta_detalle": html_lib.unescape(enlace.group(1)),
            })
    total = re.search(r"\d+ a \d+ de (\d+)", _texto(pagina))
    return filas, int(total.group(1)) if total else None


def extraer_detalle(pagina: str) -> dict:
    """Tipo de L/C, moneda, DUA y conceptos (codigo, descripcion, monto) del detalle de una LC."""
    texto = _texto(pagina)
    tipo = re.search(r"Tipo L/C:\s*(\d{4})", texto)
    dua = re.search(r"(?:DUA|DAM) (\d{3}-\d{4}-\d{2}-\d+)", texto)
    conceptos = []
    for fila in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", pagina):
        celdas = [_texto(c) for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", fila)]
        if len(celdas) == 3 and re.fullmatch(r"\d{4}", celdas[0]) and re.fullmatch(r"[\d,.]+", celdas[2]):
            conceptos.append({"codigo": celdas[0], "descripcion": celdas[1], "monto": _monto(celdas[2])})
    return {
        "tipo": tipo.group(1) if tipo else "",
        "moneda": "USD" if "en DOLARES" in texto.upper() else "PEN",
        "dua": dua.group(1) if dua else "",
        "conceptos": conceptos,
    }


class _Cliente:
    def __init__(self):
        self.sesion = requests.Session()

    def pedir(self, url: str, datos: dict | None = None) -> str:
        ultimo = None
        for intento in range(3):
            try:
                r = (self.sesion.post(url, data=datos, timeout=40) if datos is not None
                     else self.sesion.get(url, timeout=40))
                if r.status_code == 200:
                    return r.content.decode("latin-1")
                ultimo = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                ultimo = e.__class__.__name__
            time.sleep(5 * (intento + 1))
        raise ErrorAduanas(f"La consulta de Aduanas no respondió ({ultimo}).")


def _listar_mes(cliente: _Cliente, ruc: str, ini: date, fin: date) -> list[dict]:
    pagina = cliente.pedir(URL_LISTADO, {
        "accion": "LiquidaMostrarListado", "rlestado": "CAN", "rlcoddes": "9999", "rlcodruc": ruc,
        "rlfecliq_ini": ini.strftime("%d/%m/%Y"), "rlfecliq_fin": fin.strftime("%d/%m/%Y"),
    })
    filas, total = extraer_listado(pagina)
    pagina_actual = 1
    while total is not None and len(filas) < total and pagina_actual < MAX_PAGINAS:
        time.sleep(PAUSA_SEG)
        siguiente, _ = extraer_listado(cliente.pedir(URL_INICIO, {"currPage": str(pagina_actual), "Action": "next"}))
        nuevas = [f for f in siguiente if f["lc"] not in {x["lc"] for x in filas}]
        if not nuevas:
            break
        filas += nuevas
        pagina_actual += 1
    if total is not None and len(filas) < total:
        raise ErrorAduanas(f"Aduanas lista {total} liquidaciones en {ini:%m/%Y} y solo se pudieron leer {len(filas)}.")
    return filas


def leer_percepciones_importacion(ruc: str, desde: date, hasta: date) -> list[dict]:
    """
    Percepciones de IGV (LC tipo 0038 canceladas) liquidadas entre desde y
    hasta, con los campos de LiquidacionRetencionPercepcion.
    """
    cliente = _Cliente()
    cliente.pedir(URL_INICIO)  # abre la sesion de la consulta (cookie)
    percepciones = []
    for ini, fin in meses(desde, hasta):
        time.sleep(PAUSA_SEG)
        for lc in _listar_mes(cliente, ruc, ini, fin):
            time.sleep(PAUSA_SEG)
            detalle = extraer_detalle(cliente.pedir(f"{URL_DETALLE}?{lc['consulta_detalle']}"))
            if detalle["tipo"] != TIPO_PERCEPCION:
                continue
            monto = sum(c["monto"] for c in detalle["conceptos"] if c["codigo"] == CONCEPTO_PERCEPCION)
            if detalle["moneda"] != "PEN":
                logger.warning(f"Aduanas {ruc}: la LC {lc['lc']} de percepcion viene en {detalle['moneda']}")
            fecha_liq = lc["fecha_liquidacion"]
            percepciones.append({
                "ruc_agente": RUC_SUNAT_ADUANAS,
                "documento": lc["lc"],
                "fecha_emision": fecha_liq,
                "fecha_pago": lc["fecha_cancelacion"],
                "periodo": fecha_liq[:7] if fecha_liq else f"{ini:%Y-%m}",
                "monto": round(monto, 2),
                "cuenta": bool(lc["fecha_cancelacion"]),
                "referencia": detalle["dua"],
            })
    logger.info(f"Aduanas {ruc}: {len(percepciones)} percepcion(es) entre {desde} y {hasta}")
    return percepciones
