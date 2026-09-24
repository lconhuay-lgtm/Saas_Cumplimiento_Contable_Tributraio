#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Adaptador del motor SUNAT -- Fase 1, extendido para descargar documentos
(mejora post-Fase 2).

Interfaz unica que el resto del sistema (worker, endpoints) usa para
consultar el buzon de una empresa, sin conocer los detalles de Selenium.
Disenado para que agregar otro adaptador (SUNAFIL, otro pais) sea agregar
un modulo nuevo con la misma firma de salida, no reescribir el llamador.

Descarga de documentos: reutiliza _descargar_documento_constancia() de
web_navigation.py, que ya es el metodo probado en produccion por la
automatizacion original para bajar el PDF de una notificacion. Solo se
descarga el documento de los mensajes que el llamador marca como "nuevos"
(via ids_conocidos) -- evita re-descargar mensajes ya vistos en corridas
anteriores, y evita el costo de abrir una sesion aparte solo para bajar un
documento (se hace dentro de la misma sesion ya autenticada).
"""
import os
import time
import base64
import logging
import hashlib
from urllib.parse import urlparse, parse_qs, urljoin

import config
from web_navigation import SunatWebNavigator
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger("core_scraper.adapter")

# Limite de documentos a descargar por corrida -- una empresa con muchos
# mensajes nuevos de una sola vez (poco comun, pero posible si es la
# primera consulta despues de mucho tiempo) no debe alargar la sesion
# indefinidamente; el resto queda pendiente para la proxima consulta.
MAX_DESCARGAS_POR_CORRIDA = int(os.environ.get("SUNAT_MAX_DESCARGAS_POR_CORRIDA", 10))


def mensaje_id(fecha: str, asunto: str) -> str:
    """
    Identificador estable de un mensaje -- MISMO criterio que usa
    backend/app/jobs.py (fecha+asunto). Vive aca tambien porque este modulo
    necesita saber, durante el scraping, si un mensaje ya es conocido o es
    nuevo (para decidir si vale la pena descargar su documento). Si esta
    funcion cambia, jobs.py debe cambiar igual o dejan de coincidir.
    """
    return hashlib.sha256(f"{fecha}|{asunto}".encode("utf-8")).hexdigest()


def consultar_buzon(
    ruc: str,
    usuario_sol: str,
    clave_sol: str,
    razon_social: str = "",
    headless: bool = True,
    limite_mensajes: int = 20,
    ids_conocidos: set | None = None,
    descargar_documentos: bool = True,
    on_progreso=None,
) -> dict:
    """
    Inicia sesion en SUNAT SOL y devuelve el listado de mensajes visibles
    en el Buzon de Notificaciones. Si se pasa ids_conocidos (los
    mensaje_externo_id que el llamador ya tiene guardados para esta
    empresa) y descargar_documentos=True, tambien descarga el PDF de los
    mensajes que NO esten en ese set, dentro de la misma sesion.

    Ademas del Buzon, entra brevemente a la Ficha RUC (sin generar ningun
    PDF, solo lee texto -- unos 8-10 segundos extra) para capturar el
    "Estado del Contribuyente" (Activo / Baja de Oficio / etc.), que a
    diferencia de la razon social y la condicion de domicilio NO aparece
    en el navbar normal del Menu SOL (confirmado con un diagnostico real).
    Se hace en TODAS las consultas (incluido el chequeo automatico de las
    11am/7:30pm) para que el aviso de cambios en el Dashboard funcione
    para cualquier empresa, no solo las que alguien genere una Ficha RUC a
    mano -- decision del usuario del producto, dado el impacto de una baja
    de oficio en la declaracion de impuestos.

    on_progreso: callback opcional, se llama con un string de etapa
    ("iniciando_sesion", "autenticando", "leyendo_estado", "abriendo_buzon",
    "leyendo_mensajes", "descargando_documentos") en cada punto de avance
    -- mismo patron que generar_ficha_ruc_pdf(on_progreso=...), para que el
    llamador (jobs.py) pueda mostrar una barra de progreso real en el
    boton "Consultar" de cada empresa. Un fallo del callback en si nunca
    debe tumbar la consulta.

    Returns:
        dict: {
            "ok": bool,
            "mensajes": [{"fecha": str, "asunto": str}, ...],
            "documentos": {mensaje_id: ruta_local_del_pdf, ...},
            "razon_social_sunat": str | None,  # nombre real segun SUNAT
            "condicion_domicilio": str | None,  # Habido / No Habido / No Hallado
            "estado_contribuyente": str | None,  # Activo / Baja de Oficio / etc.
            "flujo_detectado": str | None,  # "flujo1" / "flujo2" / "sin_flujo" (Fase 3)
            "error": str | None,
        }
    """

    def _reportar(etapa: str):
        if on_progreso is None:
            return
        try:
            on_progreso(etapa)
        except Exception as e:
            logger.warning(f"El callback de progreso fallo (no es grave, se sigue con la consulta igual): {e}")

    empresa = {"ruc": ruc, "usuario": usuario_sol, "clave": clave_sol, "razon_social": razon_social}
    navegador = SunatWebNavigator(empresa=empresa, headless=headless)
    try:
        if not navegador.initialize_browser():
            return {"ok": False, "mensajes": [], "documentos": {}, "razon_social_sunat": None, "condicion_domicilio": None, "estado_contribuyente": None, "flujo_detectado": None, "error": "No se pudo iniciar el navegador"}

        _reportar("iniciando_sesion")
        navegador.driver.get(config.URL_SUNAT)
        time.sleep(3)

        _reportar("autenticando")
        if not navegador._hacer_clicks_sunat(empresa):
            return {"ok": False, "mensajes": [], "documentos": {}, "razon_social_sunat": navegador.razon_social_detectada, "condicion_domicilio": navegador.condicion_domicilio_detectada, "estado_contribuyente": None, "flujo_detectado": navegador.flujo_detectado, "error": "No se pudo iniciar sesion en SUNAT (revisa usuario/clave)"}

        # Se hace ANTES de navegar al Buzon (no despues) porque el
        # desplegable del nombre y el boton "Ver Ficha Ruc" viven en esta
        # misma pantalla del Menu SOL -- entrar al Buzon primero implicaria
        # tener que volver aca despues, mas navegacion y mas riesgo de
        # fallo. Un fallo leyendo esto NUNCA debe tumbar el resto de la
        # consulta (ver _leer_estado_contribuyente).
        _reportar("leyendo_estado")
        navegador.estado_contribuyente_detectado = navegador._leer_estado_contribuyente()

        _reportar("abriendo_buzon")
        if not navegador._navegar_a_buzon_notificaciones():
            return {"ok": False, "mensajes": [], "documentos": {}, "razon_social_sunat": navegador.razon_social_detectada, "condicion_domicilio": navegador.condicion_domicilio_detectada, "estado_contribuyente": navegador.estado_contribuyente_detectado, "flujo_detectado": navegador.flujo_detectado, "error": "Se inicio sesion pero no se pudo abrir el Buzon Electronico"}

        _reportar("leyendo_mensajes")
        mensajes = _leer_lista_mensajes(navegador, limite_mensajes)

        documentos = {}
        if descargar_documentos and ids_conocidos is not None:
            _reportar("descargando_documentos")
            try:
                documentos = _descargar_documentos_nuevos(navegador, ids_conocidos, limite_mensajes)
            except Exception as e:
                # Un fallo descargando documentos NUNCA debe tumbar la
                # consulta completa -- los mensajes ya se leyeron bien, eso
                # es lo importante. El documento se puede intentar de nuevo
                # en la proxima consulta (sigue sin estar en ids_conocidos
                # porque el mensaje en si si se guarda igual).
                logger.error(f"Error general descargando documentos para {ruc}: {e}")

        return {
            "ok": True,
            "mensajes": mensajes,
            "documentos": documentos,
            "razon_social_sunat": navegador.razon_social_detectada,
            "condicion_domicilio": navegador.condicion_domicilio_detectada,
            "estado_contribuyente": navegador.estado_contribuyente_detectado,
            "flujo_detectado": navegador.flujo_detectado,
            "error": None,
        }

    except Exception as e:
        logger.error(f"Error consultando buzon de {ruc}: {e}")
        return {"ok": False, "mensajes": [], "documentos": {}, "razon_social_sunat": None, "condicion_domicilio": None, "estado_contribuyente": None, "flujo_detectado": None, "error": str(e)}
    finally:
        navegador.close_browser()


def preparar_ingreso_directo(ruc: str = "", headless: bool = False) -> dict:
    """
    "Ingreso directo": en vez de loguearse con Selenium y devolver los
    mensajes del buzon (como consultar_buzon), esta funcion se DETIENE
    justo antes de escribir ninguna credencial -- solo llega hasta la
    pantalla de login de SUNAT (web_navigation.obtener_url_login()) y
    devuelve los datos que hacen falta para armar, en el backend, un
    formulario oculto que se autoenvia EN EL NAVEGADOR REAL DEL USUARIO
    (ver backend/app/routers/empresas.py, que es quien de verdad tiene y
    embebe el RUC/usuario/clave -- esta funcion no los necesita, solo
    llega hasta la pantalla de login sin identificarse). Asi la persona
    termina en una pestaña de SUNAT genuinamente logueada, sin escribir
    nada -- la clave SOL viaja del backend al navegador del usuario una
    sola vez, dentro del HTML de esa respuesta, nunca hacia SUNAT desde
    este servidor.

    La URL de login de SUNAT incluye un parametro `state` (y `originalUrl`)
    que SUNAT genera de nuevo en cada sesion -- por eso hace falta abrir un
    navegador real cada vez que se usa esta funcion, no se puede guardar
    el resultado de una vez para la siguiente.

    `ruc` es solo para identificar en los logs a que empresa correspondia
    este intento (no se usa para nada dentro de la funcion en si).

    Returns:
        dict: {
            "ok": bool,
            "accion_url": str | None,   # URL absoluta de destino del POST (j_security_check)
            "state": str | None,
            "original_url": str | None,
            "lang": str | None,
            "error": str | None,
        }
    """
    vacio = {"ok": False, "accion_url": None, "state": None, "original_url": None, "lang": None, "error": None}

    navegador = SunatWebNavigator(empresa=None, headless=headless)
    try:
        if not navegador.initialize_browser():
            return {**vacio, "error": "No se pudo iniciar el navegador"}

        navegador.driver.get(config.URL_SUNAT)
        # Sin sleep fijo aca: el primer paso de obtener_url_login() ya
        # espera (con wait.until, con polling) a que el boton de la
        # portada este presente antes de seguir -- un sleep(3) antes de
        # eso solo sumaba tiempo muerto sin aportar nada.

        url_login = navegador.obtener_url_login()
        if not url_login:
            return {**vacio, "error": "No se pudo llegar a la pantalla de login de SUNAT"}

        partes = urlparse(url_login)
        query = parse_qs(partes.query)
        state = query.get("state", [None])[0]
        original_url = query.get("originalUrl", [None])[0]
        lang = query.get("lang", ["es-PE"])[0]
        # La accion del formulario de login es relativa ("j_security_check")
        # -- se resuelve contra la URL actual, reemplazando el ultimo tramo
        # (loginMenuSol -> j_security_check), igual que haria el navegador.
        accion_url = urljoin(url_login, "j_security_check")

        return {
            "ok": True,
            "accion_url": accion_url,
            "state": state,
            "original_url": original_url,
            "lang": lang,
            "error": None,
        }

    except Exception as e:
        logger.error(f"Error preparando el ingreso directo para {ruc}: {e}")
        return {**vacio, "error": str(e)}
    finally:
        navegador.close_browser()


def _escanear_mensajes(navegador, limite):
    """
    Escanea el listado visible en el Buzon Electronico y devuelve, por cada
    mensaje, su fecha/asunto (para guardar en la base) y el elemento <a>
    clickeable (para poder entrar a descargar su documento). Se separa de
    _leer_lista_mensajes porque ese solo necesita texto -- aca ademas
    necesitamos la referencia al elemento del DOM.
    """
    resultado = []
    vistos = set()
    elementos_fecha = navegador.driver.find_elements(By.CLASS_NAME, "fecPublica")
    for elem_fecha in elementos_fecha[:limite]:
        texto_fecha = elem_fecha.text.strip()
        asunto = ""
        elemento_click = None
        try:
            li_padre = elem_fecha.find_element(By.XPATH, "./ancestor::li")

            posibles = li_padre.find_elements(By.TAG_NAME, "strong")
            if posibles and posibles[0].text.strip():
                asunto = posibles[0].text.strip()

            if not asunto:
                enlace = li_padre.find_element(By.TAG_NAME, "a")
                texto_enlace = enlace.text.strip()
                if texto_fecha in texto_enlace:
                    texto_enlace = texto_enlace.replace(texto_fecha, "").strip()
                asunto = texto_enlace.split("\n")[0].strip()

            if not asunto:
                texto_li = li_padre.text.strip()
                if texto_fecha in texto_li:
                    texto_li = texto_li.replace(texto_fecha, "").strip()
                asunto = texto_li.split("\n")[0].strip()

            try:
                elemento_click = li_padre.find_element(By.TAG_NAME, "a")
            except Exception:
                elemento_click = None
        except Exception:
            pass

        asunto = asunto or "(sin asunto)"
        clave = (texto_fecha, asunto)
        if clave in vistos:
            continue
        vistos.add(clave)
        resultado.append({"fecha": texto_fecha, "asunto": asunto, "elemento": elemento_click})
    return resultado


def _leer_lista_mensajes(navegador, limite):
    """Version de solo texto de _escanear_mensajes -- lo que se guarda en la base de datos."""
    return [
        {"fecha": m["fecha"], "asunto": m["asunto"]}
        for m in _escanear_mensajes(navegador, limite)
    ]


def _descargar_documentos_nuevos(navegador, ids_conocidos: set, limite: int) -> dict:
    """
    Descarga el documento (PDF) de cada mensaje que no este en
    ids_conocidos, reutilizando _descargar_documento_constancia() -- el
    metodo ya probado en produccion por la automatizacion original.

    Vuelve a escanear la lista de mensajes despues de cada descarga (en vez
    de reusar referencias de elementos ya usadas una vez) porque hacer clic
    en un mensaje y volver atras puede dejar obsoletas las referencias del
    DOM que Selenium ya tenia -- es un poco mas lento pero mucho mas
    confiable que tratar de "refrescar" las referencias viejas.

    Returns:
        dict: {mensaje_id: ruta_local_del_pdf_descargado}
    """
    descargados = {}
    intentados = set()
    descargas_exitosas = 0
    # Acumulativo desde ANTES de la primera descarga de esta corrida, no
    # "antes/despues" de cada intento individual -- si se compara solo
    # contra el listado inmediatamente anterior, un archivo que ya estaba
    # en la carpeta de descargas de una corrida previa del mismo dia (por
    # ejemplo, un intento fallido que dejo el PDF a medio nombrar) puede
    # hacer que un documento recien descargado no se reconozca como
    # "nuevo" si por cualquier motivo el nombre coincide. Comparar siempre
    # contra este set acumulado evita ese caso.
    archivos_vistos = set(os.listdir(navegador.download_dir))

    while descargas_exitosas < MAX_DESCARGAS_POR_CORRIDA:
        mensajes = _escanear_mensajes(navegador, limite)

        objetivo = None
        for msg in mensajes:
            mid = mensaje_id(msg["fecha"], msg["asunto"])
            if mid in ids_conocidos or mid in intentados:
                continue
            if msg["elemento"] is None:
                intentados.add(mid)  # no hay como hacerle clic, no reintentar
                continue
            objetivo = (mid, msg)
            break

        if objetivo is None:
            break  # no quedan mensajes nuevos por descargar

        mid, msg = objetivo
        intentados.add(mid)
        logger.info(f"Descargando documento del mensaje nuevo: '{msg['asunto']}' ({msg['fecha']})")

        try:
            try:
                msg["elemento"].click()
            except Exception:
                navegador.driver.execute_script("arguments[0].click();", msg["elemento"])
            time.sleep(3)

            exito = navegador._descargar_documento_constancia()
            if exito:
                archivos_ahora = set(os.listdir(navegador.download_dir))
                nuevos_pdf = [f for f in (archivos_ahora - archivos_vistos) if f.lower().endswith(".pdf")]
                # Se actualiza el acumulado SIEMPRE (haya o no PDF nuevo)
                # para que el siguiente intento compare correctamente.
                archivos_vistos = archivos_ahora
                if nuevos_pdf:
                    ruta = os.path.join(navegador.download_dir, nuevos_pdf[0])
                    descargados[mid] = ruta
                    descargas_exitosas += 1
                    logger.info(f"Documento descargado: {ruta}")
                else:
                    logger.warning(
                        f"La descarga se reporto exitosa pero no se encontro un PDF nuevo para '{msg['asunto']}'"
                    )
            else:
                logger.warning(f"No se pudo descargar el documento de '{msg['asunto']}'")
        except Exception as e:
            logger.error(f"Error descargando documento de '{msg['asunto']}': {e}")
        finally:
            try:
                navegador.driver.back()
                time.sleep(2)
            except Exception as e:
                logger.warning(f"No se pudo volver a la lista de mensajes, se corta la descarga de documentos: {e}")
                break

    if intentados - set(descargados.keys()):
        logger.info(
            f"{len(intentados) - len(descargados)} documento(s) no se pudieron descargar en esta corrida "
            "(quedan para la proxima consulta, el mensaje en si igual se guarda)."
        )

    return descargados


def generar_ficha_ruc_pdf(
    ruc: str,
    usuario_sol: str,
    clave_sol: str,
    razon_social: str = "",
    headless: bool = True,
    on_progreso=None,
) -> dict:
    """
    Inicia sesion en SUNAT SOL, abre la "Ficha RUC" del contribuyente
    (RUC, razon social, ESTADO DEL CONTRIBUYENTE, condicion de domicilio,
    actividad economica, etc.) y genera un PDF de esa ficha.

    on_progreso: callback opcional, se llama con un string de etapa
    ("iniciando_sesion", "autenticando", "abriendo_ficha", "generando_pdf")
    en cada punto de avance -- solo para que el llamador (jobs.py) pueda
    ir guardando el progreso y el frontend mostrar una barra con
    perspectiva real del tiempo que falta, en vez de un spinner opaco. Un
    fallo del callback en si (p.ej. la base de datos no responde un
    instante) NUNCA debe tumbar la generacion del PDF.

    Logica verificada con un diagnostico real contra produccion
    (diagnostico_ficha_ruc.py) antes de incorporarla aca:
      1. El boton "Ver Ficha Ruc" vive en el desplegable que se abre al
         hacer clic en el nombre de la empresa (#aOpcionUsuario2) del
         navbar del Menu SOL.
      2. El contenido de la Ficha RUC se carga dentro de un iframe
         (#iframeApplication) cuyo src es una URL de "accion" identificable
         (MenuInternet.htm?action=execute&code=10.1.1.1.1&...).
      3. El boton "Imprimir" real de SUNAT solo llama a
         iframe.contentWindow.print() -- abre el dialogo nativo del SO, que
         no se puede automatizar. En su lugar, se abre ese MISMO src en una
         pestaña nueva (la sesion ya esta autenticada via cookies, carga
         igual) y se usa el comando de Chrome DevTools Page.printToPDF, que
         genera el PDF directamente sin ningun dialogo.

    Returns:
        dict: {"ok": bool, "pdf_bytes": bytes | None, "error": str | None}
    """

    def _reportar(etapa: str):
        if on_progreso is None:
            return
        try:
            on_progreso(etapa)
        except Exception as e:
            logger.warning(f"El callback de progreso fallo (no es grave, se sigue generando igual): {e}")

    empresa = {"ruc": ruc, "usuario": usuario_sol, "clave": clave_sol, "razon_social": razon_social}
    navegador = SunatWebNavigator(empresa=empresa, headless=headless)
    try:
        if not navegador.initialize_browser():
            return {"ok": False, "pdf_bytes": None, "error": "No se pudo iniciar el navegador"}

        _reportar("iniciando_sesion")
        navegador.driver.get(config.URL_SUNAT)
        time.sleep(3)

        _reportar("autenticando")
        if not navegador._hacer_clicks_sunat(empresa):
            return {"ok": False, "pdf_bytes": None, "error": "No se pudo iniciar sesion en SUNAT (revisa usuario/clave)"}

        driver = navegador.driver

        _reportar("abriendo_ficha")
        logger.info(f"Abriendo el desplegable del nombre de la empresa para {ruc}...")
        boton_nombre = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "aOpcionUsuario2"))
        )
        try:
            boton_nombre.click()
        except Exception:
            driver.execute_script("arguments[0].click();", boton_nombre)
        time.sleep(2)

        boton_ficha = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "btnFichaRuc"))
        )
        try:
            boton_ficha.click()
        except Exception:
            driver.execute_script("arguments[0].click();", boton_ficha)

        logger.info("Clic en 'Ver Ficha Ruc' hecho, esperando a que cargue el contenido...")
        time.sleep(6)

        try:
            iframe_el = driver.find_element(By.ID, "iframeApplication")
            src_iframe = iframe_el.get_attribute("src")
        except Exception as e:
            return {"ok": False, "pdf_bytes": None, "error": f"No se encontro el contenido de la Ficha RUC: {e}"}

        if not src_iframe:
            return {"ok": False, "pdf_bytes": None, "error": "La Ficha RUC no devolvio una direccion valida para generar el PDF"}

        ventana_original = driver.current_window_handle
        driver.execute_script("window.open(arguments[0], '_blank');", src_iframe)
        time.sleep(2)
        ventanas_nuevas = [w for w in driver.window_handles if w != ventana_original]
        if not ventanas_nuevas:
            return {"ok": False, "pdf_bytes": None, "error": "No se pudo abrir la Ficha RUC en una pestaña nueva"}
        driver.switch_to.window(ventanas_nuevas[-1])
        time.sleep(4)

        # La pestaña que se acaba de abrir TODAVIA no es la Ficha RUC
        # completa -- es la pantalla "Datos de Ficha RUC - Modificacion..."
        # (un formulario de edicion con los botones "Descargar Ficha RUC /
        # Ficha RUC / Aceptar / Cancelar" alrededor de los mismos datos).
        # Confirmado con un diagnostico real (comparando el PDF de antes y
        # despues de este cambio): hay que hacer clic en el boton interno
        # "Ficha RUC" (un <input type="submit" value="Ficha RUC">) para que
        # SUNAT genere la "CIR - Constancia de Informacion Registrada"
        # real -- el documento oficial, con el domicilio fiscal detallado,
        # documento de identidad y tributos afectos que NO salian en la
        # pantalla de edicion. Si el boton no aparece (SUNAT cambia su
        # marcado, o este tipo de contribuyente no lo tiene) no se corta la
        # generacion -- se sigue con lo que ya cargo, que sigue siendo
        # mejor que nada.
        try:
            boton_ficha_interno = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((
                    By.XPATH,
                    "//input[@value='Ficha RUC'] | //button[normalize-space()='Ficha RUC']"
                ))
            )
            ventanas_antes_del_clic = set(driver.window_handles)
            try:
                boton_ficha_interno.click()
            except Exception:
                driver.execute_script("arguments[0].click();", boton_ficha_interno)
            time.sleep(4)
            # Si el clic abrio una pestaña nueva nos cambiamos a esa; si
            # navego en la misma (lo mas probable, es un submit de
            # formulario) seguimos en la que ya estabamos.
            ventanas_nuevas_tras_clic = set(driver.window_handles) - ventanas_antes_del_clic
            if ventanas_nuevas_tras_clic:
                driver.switch_to.window(list(ventanas_nuevas_tras_clic)[-1])
        except Exception as e:
            logger.warning(
                f"No se encontro el boton interno 'Ficha RUC' para {ruc} -- se genera el PDF con lo que ya "
                f"cargo (puede faltar el domicilio fiscal detallado y otros datos ampliados): {e}"
            )

        _reportar("generando_pdf")
        try:
            resultado_pdf = driver.execute_cdp_cmd("Page.printToPDF", {
                "printBackground": True,
                "preferCSSPageSize": True,
            })
            pdf_bytes = base64.b64decode(resultado_pdf["data"])
        finally:
            try:
                driver.close()
                driver.switch_to.window(ventana_original)
            except Exception as e:
                logger.warning(f"No se pudo volver a la ventana original despues de generar el PDF: {e}")

        if not pdf_bytes:
            return {"ok": False, "pdf_bytes": None, "error": "El PDF generado quedo vacio"}

        logger.info(f"Ficha RUC generada correctamente para {ruc} ({len(pdf_bytes)} bytes)")
        return {"ok": True, "pdf_bytes": pdf_bytes, "error": None}

    except Exception as e:
        logger.error(f"Error generando la Ficha RUC de {ruc}: {e}")
        return {"ok": False, "pdf_bytes": None, "error": str(e)}
    finally:
        navegador.close_browser()
