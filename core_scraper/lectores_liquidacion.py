"""
Lectores de SUNAT para la Liquidacion en vivo (Bloque 1 del piloto). SOLO
LECTURA: piden los mismos servicios que usan las pantallas de consulta y
nunca tocan un boton que presente, revierta o envie algo. Verificados con las
empresas piloto el 27-28/10/2026.

- leer_declaraciones_0621: casillas de cada 0621 presentado (Mis
  Declaraciones y Pagos > Consulta de Declaraciones y Pagos, exe=55.2.1.1.1).
- leer_menu_sol: en una sola sesion del Menu SOL, los comprobantes de
  retencion y de percepcion recibidos (11.5.8.1.2 y 11.5.7.1.2) y la cuenta
  de control de retenciones y percepciones del sujeto (12.8.2.1.2).
"""
import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone

import config
from adapter import (
    _abrir_opcion_menu_sol, _entrar_mis_declaraciones_y_pagos, _fecha_iso, entrar_marco_plataforma_unica,
    error_inicio_sesion,
)
from web_navigation import SunatWebNavigator

logger = logging.getLogger("core_scraper.lectores_liquidacion")

_ZONA_LIMA = timezone(timedelta(hours=-5))


def _reportero(on_progreso):
    def _reportar(etapa: str):
        if on_progreso is None:
            return
        try:
            on_progreso(etapa)
        except Exception as e:
            logger.warning(f"El callback de progreso fallo (no es grave, se sigue igual): {e}")
    return _reportar


def _texto_visible(html: str) -> str:
    sin_codigo = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    return " ".join(re.sub(r"<[^>]+>", " ", sin_codigo).replace("&nbsp;", " ").split())


# --- Declaraciones 0621 con sus casillas ---

_URL_OPCION_CONSULTA_DECLARACIONES = (
    "https://e-menu.sunat.gob.pe/cl-ti-itmenu2/MenuInternetPlataforma.htm?pestana=*&agrupacion=*&exe=55.2.1.1.1"
)
_RUTA_API_DECLARACIONES = "/v1/recaudacion/tributaria/consultadeclaracion/t/internet/declaracion"

_JS_GET_PLATAFORMA = """
var done = arguments[arguments.length - 1];
fetch(arguments[0], {credentials: 'include', headers: {
    'IdCache': sessionStorage.getItem('token'), 'IdFormulario': '*MENU*', 'Lang': 'es-PE',
    'Accept': 'application/json'}})
  .then(function (r) { return r.text().then(function (t) { done([r.status, t]); }); })
  .catch(function (e) { done([0, String(e)]); });
"""


def tramos_anuales(desde: str, hasta: str) -> list[tuple[str, str]]:
    """("2025-09", "2026-10") -> [("2025-09", "2025-12"), ("2026-01", "2026-10")]: la consulta va por ano."""
    tramos = []
    anio = int(desde[:4])
    while anio <= int(hasta[:4]):
        ini = desde if anio == int(desde[:4]) else f"{anio}-01"
        fin = hasta if anio == int(hasta[:4]) else f"{anio}-12"
        tramos.append((ini, fin))
        anio += 1
    return tramos


def casillas_0621(crudas: dict) -> dict:
    """{"C131": "29298.00 ", "C13": "02/18/2026"} -> {"131": 29298.0, "13": "02/18/2026"}."""
    casillas = {}
    for clave, valor in (crudas or {}).items():
        m = re.fullmatch(r"C(\d+)", str(clave))
        if not m:
            continue
        texto = str(valor if valor is not None else "").strip()
        try:
            casillas[m.group(1)] = float(texto)
        except ValueError:
            casillas[m.group(1)] = texto
    return casillas


def normalizar_0621(crudo: dict, casillas: dict) -> dict:
    """Un 0621 de factoriaConsulta con los campos de LiquidacionDeclaracion."""
    per = str(crudo.get("perTri") or "")
    return {
        "num_orden": str(crudo.get("numOrd") or "").strip(),
        "periodo": f"{per[:4]}-{per[4:6]}",
        # descTipoDecla: "0" original, "1" rectificatoria.
        "rectificatoria": str(crudo.get("descTipoDecla") or "0").strip() == "1",
        "fecha_presentacion": _fecha_iso(crudo.get("strFecPres")),
        "casillas": casillas_0621(casillas),
    }


def _pedir_json(driver, ruta: str):
    status, cuerpo = driver.execute_async_script(_JS_GET_PLATAFORMA, ruta)
    try:
        return status, json.loads(cuerpo) if cuerpo else None
    except ValueError:
        return status, None


def leer_declaraciones_0621(
    ruc: str,
    usuario_sol: str,
    clave_sol: str,
    razon_social: str = "",
    desde: str = "",
    hasta: str = "",
    headless: bool = True,
    on_progreso=None,
) -> dict:
    """
    Todos los 0621 presentados entre `desde` y `hasta` ("AAAA-MM"), original y
    rectificatorias, con sus casillas. La lista de factoriaConsulta ya trae las
    casillas (iguales a las del detalle en las 28 declaraciones probadas); si
    alguna llega sin ellas se pide su detalle.

    Returns:
        {"ok": bool, "error": str | None, "declaraciones": [normalizar_0621(...)]}
    """
    _reportar = _reportero(on_progreso)
    resultado_vacio = {"ok": False, "error": None, "declaraciones": []}
    empresa = {"ruc": ruc, "usuario": usuario_sol, "clave": clave_sol, "razon_social": razon_social}
    navegador = SunatWebNavigator(empresa=empresa, headless=headless)
    try:
        if not navegador.initialize_browser():
            return {**resultado_vacio, "error": "No se pudo iniciar el navegador"}

        _reportar("autenticando")
        error_login = _entrar_mis_declaraciones_y_pagos(navegador, empresa)
        if error_login:
            return {**resultado_vacio, "error": error_login, "credenciales_rechazadas": navegador.credenciales_rechazadas}

        _reportar("abriendo_declaraciones")
        driver = navegador.driver
        driver.get(_URL_OPCION_CONSULTA_DECLARACIONES)
        if not entrar_marco_plataforma_unica(driver):
            navegador._guardar_captura_error("liquidacion_0621_sin_pantalla")
            return {**resultado_vacio, "error": "La Consulta de Declaraciones y Pagos no termino de cargar"}
        time.sleep(3)

        _reportar("leyendo_declaraciones")
        driver.set_script_timeout(90)
        declaraciones = {}
        for ini, fin in tramos_anuales(desde, hasta):
            ruta = (
                f"{_RUTA_API_DECLARACIONES}/factoriaConsulta/0621/-/-/{ini[5:]}/{ini[:4]}/{fin[5:]}/{fin[:4]}/false/true"
                f"?foobar={int(time.time() * 1000)}"
            )
            status, lista = _pedir_json(driver, ruta)
            if status == 204 or (status == 200 and lista in (None, [])):
                continue
            if status != 200 or not isinstance(lista, list):
                logger.warning(f"0621 {ruc}: el tramo {ini}-{fin} respondio HTTP {status}: {str(lista)[:200]}")
                return {**resultado_vacio, "error": f"SUNAT no devolvio los 0621 de {ini} a {fin} (HTTP {status})"}
            for crudo in lista:
                if str(crudo.get("codFor") or "0621") != "0621":
                    continue
                casillas = crudo.get("casillas")
                if not casillas:
                    status_det, casillas = _pedir_json(driver, f"{_RUTA_API_DECLARACIONES}/factoriaDetalleFormulario/{crudo.get('numOrd')}")
                    if status_det != 200 or not isinstance(casillas, dict):
                        return {**resultado_vacio, "error": f"SUNAT no devolvio las casillas del 0621 orden {crudo.get('numOrd')}"}
                    time.sleep(1)
                d = normalizar_0621(crudo, casillas)
                declaraciones[d["num_orden"]] = d
            time.sleep(1)

        logger.info(f"0621 {ruc}: {len(declaraciones)} declaracion(es) entre {desde} y {hasta}")
        return {"ok": True, "error": None, "declaraciones": list(declaraciones.values())}

    except Exception as e:
        logger.error(f"Error leyendo los 0621 de {ruc}: {e}")
        return {**resultado_vacio, "error": str(e)}
    finally:
        navegador.close_browser()


# --- Menu SOL: comprobantes de retencion / percepcion recibidos ---

def _ids_menu(codigo: str) -> tuple:
    n = codigo.split(".")
    return (f"nivel1_{n[0]}", f"nivel2_{'_'.join(n[:2])}", f"nivel3_{'_'.join(n[:3])}", f"nivel4_{'_'.join(n)}")


# "Comprobante de ... Electronico > Consultar Emision y Recepcion": su boton
# Buscar hace este POST (./buscarComprobanteEmiRec) con "Recibidos" y todos los
# estados. SUNAT acepta como maximo un mes por consulta.
_COMPROBANTES_RECIBIDOS = {
    "retenciones": {"codigo": "11.5.8.1.2", "sufijo": "CompReten", "lista": "listaCompRetencion",
                    "nombre": "la consulta de comprobantes de retencion"},
    "percepciones": {"codigo": "11.5.7.1.2", "sufijo": "CompPercep", "lista": "listaCompPercepcion",
                     "nombre": "la consulta de comprobantes de percepcion"},
}

_JS_POST_FORMULARIO = """
var done = arguments[arguments.length - 1];
fetch(arguments[0], {method: 'POST', credentials: 'include', body: new URLSearchParams(arguments[1]),
    headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}})
  .then(function (r) { return r.text().then(function (t) { done([r.status, t]); }); })
  .catch(function (e) { done([0, String(e)]); });
"""


def normalizar_comprobante_recibido(crudo: dict, fuente: str) -> dict:
    """
    Un comprobante de listaCompRetencion / listaCompPercepcion. codEstadoCpe:
    "01" emitido, "02" revertido (no cuenta). La fecha llega en milisegundos.
    """
    # El de percepciones todavia no se vio con datos: si no se llama asi, vale
    # el primer "montoTotal..." que traiga valor.
    clave_esperada = "montoTotalRetenido" if fuente == "retenciones" else "montoTotalPercibido"
    clave_monto = next(
        (k for k in [clave_esperada, *crudo] if k.lower().startswith("montototal") and crudo.get(k) is not None), None
    )
    try:
        fecha = datetime.fromtimestamp(int(crudo.get("fechaEmision")) / 1000, _ZONA_LIMA).date()
    except (TypeError, ValueError):
        fecha = None
    estado = str(crudo.get("codEstadoCpe") or "").strip()
    try:
        monto = round(float(crudo.get(clave_monto) or 0), 2) if clave_monto else 0.0
    except (TypeError, ValueError):
        monto = 0.0
    return {
        "ruc_agente": str(crudo.get("numRuc") or "").strip(),
        "documento": f"{str(crudo.get('numSerieCpe') or '').strip()}-{str(crudo.get('numCpe') or '').strip()}",
        "fecha_emision": fecha.isoformat() if fecha else None,
        "periodo": fecha.strftime("%Y-%m") if fecha else "",
        "monto": monto,
        "cuenta": estado == "01",
        "monto_sin_clave": clave_monto is None,
    }


def _leer_comprobantes_recibidos(navegador, fuente: str, desde: date, hasta: date) -> dict:
    datos = _COMPROBANTES_RECIBIDOS[fuente]
    error_menu = _abrir_opcion_menu_sol(navegador, _ids_menu(datos["codigo"]), datos["codigo"], datos["nombre"])
    if error_menu:
        return {"ok": False, "error": error_menu, "filas": []}
    driver = navegador.driver
    for _ in range(30):
        if driver.execute_script("return !!document.getElementById('btnBuscar')"):
            break
        time.sleep(1)
    else:
        navegador._guardar_captura_error(f"liquidacion_{fuente}_sin_formulario")
        return {"ok": False, "error": f"No termino de cargar {datos['nombre']}", "filas": []}

    suf = datos["sufijo"]
    cuerpo = {
        f"opcionTipo{suf}": "recibido", "tipoDocReceptor": "000", "numDocReceptor": "",
        f"serie{suf}": "", f"numero{suf}": "",
        "fechaInicio": desde.strftime("%d/%m/%Y"), "fechaFin": hasta.strftime("%d/%m/%Y"),
        f"estado{suf}": "000",
    }
    driver.set_script_timeout(90)
    status, texto = driver.execute_async_script(_JS_POST_FORMULARIO, "./buscarComprobanteEmiRec", cuerpo)
    try:
        respuesta = json.loads(texto) if status == 200 else None
    except ValueError:
        respuesta = None
    if not isinstance(respuesta, dict) or not isinstance(respuesta.get(datos["lista"]), list):
        logger.warning(f"{fuente} {navegador.empresa.get('ruc')}: respuesta inesperada (HTTP {status}): {str(texto)[:200]}")
        return {"ok": False, "error": f"SUNAT no devolvio {datos['nombre']} (HTTP {status})", "filas": []}
    filas = [normalizar_comprobante_recibido(c, fuente) for c in respuesta[datos["lista"]]]
    if any(f["monto_sin_clave"] for f in filas):
        logger.warning(f"{fuente}: comprobante sin campo de monto conocido; claves {list(respuesta[datos['lista']][0])}")
    return {"ok": True, "error": None, "filas": filas}


# --- Menu SOL: cuenta de control (Consulto mis Retenciones y Percepciones IGV - Sujeto) ---

_CODIGO_CUENTA_CONTROL = "12.8.2.1.2"
# Para las percepciones de importacion SUNAT figura como agente con este RUC.
RUC_SUNAT_ADUANAS = "20131312955"
# (tipo, tipoConsulta del formulario, RUC del agente; "" = todos los agentes)
CONSULTAS_CUENTA_CONTROL = (
    ("retencion", "01", ""),
    ("percepcion", "02", ""),
    ("percepcion", "02", RUC_SUNAT_ADUANAS),
)
_INTENTOS_CUENTA_CONTROL = 3

# Llena el formulario y pulsa SOLO "Consultar" (verifica el texto del boton:
# no tiene id). window.__antes marca la pagina del formulario para saber
# cuando ya cargo la de resultados.
_JS_CONSULTAR_CUENTA_CONTROL = """
var tipo = arguments[0], mi = arguments[1], ai = arguments[2], mf = arguments[3], af = arguments[4], ruc = arguments[5];
function poner(n, v) {
    var e = document.getElementsByName(n)[0] || document.getElementById(n);
    if (!e) return false;
    e.value = v;
    e.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
}
var ok = [poner('tipoConsulta', tipo), poner('mesi', mi), poner('anoi', ai), poner('mesf', mf), poner('anof', af),
          poner('documento', ruc)];
if (ok.indexOf(false) >= 0) return 'faltan campos ' + ok;
var b = document.getElementsByName('btnConsultar')[0];
var texto = b ? (b.value || b.textContent || '').replace(/[\\s\\u00a0]+/g, ' ').trim() : '';
if (texto !== 'Consultar') return 'sin boton Consultar [' + texto + ']';
window.__antes = true;
b.click();
return 'ok';
"""


def _monto_entero(texto: str) -> float:
    try:
        return float(texto.replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def extraer_cuenta_control(html: str) -> list[dict] | None:
    """
    Filas "Periodo | Monto total pagado (o percibido) | Monto total retenido
    (o percepcion)" de la pantalla de resultados. [] si SUNAT dice que no hay
    datos; None si la pagina no es la de resultados.
    """
    filas = []
    for fila in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", html):
        celdas = [_texto_visible(c) for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", fila)]
        if len(celdas) >= 3 and re.fullmatch(r"\d{6}", celdas[0]):
            filas.append({
                "periodo": f"{celdas[0][:4]}-{celdas[0][4:]}",
                "monto_base": _monto_entero(celdas[1]),
                "monto": _monto_entero(celdas[2]),
            })
    if filas:
        return filas
    texto = _texto_visible(html)
    if "Monto Total" in texto or re.search(r"(?i)\bno (se )?(han )?(encontr|registr|exist|tiene|hay)", texto):
        return []
    return None


# Sin datos para la consulta, SUNAT no muestra tabla sino un alert(): "Sr.
# Contribuyente, no se cuenta con informacion para los filtros ingresados."
_AVISO_SIN_DATOS = "no se cuenta con informaci"


def _aceptar_alerta(driver) -> str | None:
    """Texto del alert() abierto (y lo cierra), o None si no hay ninguno."""
    try:
        alerta = driver.switch_to.alert
        texto = alerta.text or ""
        alerta.accept()
        return texto
    except Exception:
        return None


def _hay_formulario_cuenta_control(driver) -> bool:
    try:
        return bool(driver.execute_script("return document.getElementsByName('btnConsultar').length > 0"))
    except Exception:
        return False


def _leer_cuenta_control(navegador, desde: str, hasta: str) -> dict:
    """
    Las 3 consultas de CONSULTAS_CUENTA_CONTROL; cada una se guarda aparte
    aunque otra falle. Volver a abrir la opcion del menu para la segunda
    consulta hacia que SUNAT respondiera "no podemos atenderlo" (28/10/2026,
    BASCAT y CKM: siempre funcionaba solo la primera), asi que las siguientes
    se hacen desde el formulario que trae la misma pantalla de resultados.
    """
    driver = navegador.driver
    filas, grupos, errores = [], [], []
    for tipo, tipo_consulta, ruc_agente in CONSULTAS_CUENTA_CONTROL:
        resultado = None
        for intento in range(1, _INTENTOS_CUENTA_CONTROL + 1):
            if _hay_formulario_cuenta_control(driver):
                time.sleep(3)
            else:
                error_menu = _abrir_opcion_menu_sol(
                    navegador, _ids_menu(_CODIGO_CUENTA_CONTROL), _CODIGO_CUENTA_CONTROL, "la cuenta de control"
                )
                if error_menu:
                    resultado = error_menu
                    break
                for _ in range(30):
                    if _hay_formulario_cuenta_control(driver):
                        break
                    time.sleep(1)
                # Consultar apenas aparece el boton dio "no podemos atenderlo";
                # la exploracion que funciono esperaba unos segundos.
                time.sleep(6)
            estado = driver.execute_script(
                _JS_CONSULTAR_CUENTA_CONTROL, tipo_consulta, desde[5:], desde[:4], hasta[5:], hasta[:4], ruc_agente
            )
            if estado != "ok":
                resultado = f"no se pudo llenar el formulario ({estado})"
                break
            html, alerta = "", None
            for _ in range(45):
                time.sleep(1)
                alerta = _aceptar_alerta(driver)
                if alerta is not None:
                    break
                try:
                    if driver.execute_script("return !window.__antes && document.readyState === 'complete'"):
                        html = driver.page_source
                        break
                except Exception:
                    continue
            if alerta is not None:
                if _AVISO_SIN_DATOS in alerta.lower():
                    resultado = []
                else:
                    resultado = f"SUNAT mostró el aviso: {alerta[:200]}"
                break
            if "no podemos atenderlo" in html:
                logger.warning(
                    f"Cuenta de control {navegador.empresa.get('ruc')} {tipo} {ruc_agente or 'todos'}: "
                    f"SUNAT no atendio (intento {intento})"
                )
                if intento == 1:
                    navegador._guardar_captura_error("liquidacion_cuenta_control_no_atendio")
                resultado = "SUNAT respondio 'En estos momentos no podemos atenderlo'"
                time.sleep(20 * intento)
                continue
            leidas = extraer_cuenta_control(html) if html else None
            if leidas is None:
                navegador._guardar_captura_error("liquidacion_cuenta_control_sin_resultado")
                resultado = "la pantalla de resultados no cargo"
                break
            resultado = leidas
            break
        if isinstance(resultado, list):
            filas += [{**f, "tipo": tipo, "ruc_agente": ruc_agente} for f in resultado]
            grupos.append((tipo, ruc_agente))
        else:
            errores.append(f"{tipo}{' ' + ruc_agente if ruc_agente else ''}: {resultado}")
        time.sleep(2)
    return {"ok": not errores, "error": "; ".join(errores) or None, "filas": filas, "grupos": grupos}


def leer_menu_sol(
    ruc: str,
    usuario_sol: str,
    clave_sol: str,
    razon_social: str = "",
    retenciones: tuple[date, date] | None = None,
    percepciones: tuple[date, date] | None = None,
    cuenta_control: tuple[str, str] | None = None,
    headless: bool = True,
    on_progreso=None,
) -> dict:
    """
    Una sola sesion del Menu SOL para las lecturas pedidas:
    - retenciones / percepciones: (desde, hasta) por fecha de emision, maximo un mes.
    - cuenta_control: ("AAAA-MM", "AAAA-MM"), maximo 12 periodos y antes del mes actual.

    Returns:
        {"ok": bool (entro al Menu SOL), "error": str | None, "credenciales_rechazadas": bool,
         "resultados": {"retenciones": {"ok", "error", "filas"}, "percepciones": {...},
                        "cuenta_control": {"ok", "error", "filas", "grupos"}}}
    """
    _reportar = _reportero(on_progreso)
    resultado_vacio = {"ok": False, "error": None, "resultados": {}}
    empresa = {"ruc": ruc, "usuario": usuario_sol, "clave": clave_sol, "razon_social": razon_social}
    navegador = SunatWebNavigator(empresa=empresa, headless=headless)
    resultados = {}
    try:
        if not navegador.initialize_browser():
            return {**resultado_vacio, "error": "No se pudo iniciar el navegador"}

        _reportar("iniciando_sesion")
        navegador.driver.get(config.URL_SUNAT)
        time.sleep(3)
        _reportar("autenticando")
        if not navegador._hacer_clicks_sunat(empresa):
            return {**resultado_vacio, "error": error_inicio_sesion(navegador), "credenciales_rechazadas": navegador.credenciales_rechazadas}

        for fuente, rango in (("retenciones", retenciones), ("percepciones", percepciones)):
            if rango is None:
                continue
            _reportar(f"leyendo_{fuente}")
            try:
                resultados[fuente] = _leer_comprobantes_recibidos(navegador, fuente, *rango)
            except Exception as e:
                logger.error(f"Error leyendo {fuente} de {ruc}: {e}")
                resultados[fuente] = {"ok": False, "error": str(e)[:300], "filas": []}
            time.sleep(2)

        if cuenta_control is not None:
            _reportar("leyendo_cuenta_control")
            try:
                resultados["cuenta_control"] = _leer_cuenta_control(navegador, *cuenta_control)
            except Exception as e:
                logger.error(f"Error leyendo la cuenta de control de {ruc}: {e}")
                resultados["cuenta_control"] = {"ok": False, "error": str(e)[:300], "filas": [], "grupos": []}

        return {"ok": True, "error": None, "resultados": resultados}

    except Exception as e:
        logger.error(f"Error en el Menu SOL de {ruc}: {e}")
        return {**resultado_vacio, "error": str(e), "resultados": resultados}
    finally:
        navegador.close_browser()
