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
import html as html_lib
import json
import re
from datetime import date, datetime, timedelta, timezone
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


# Fragmento que el frontend busca (empresas/page.js, ERROR_CREDENCIALES_INCORRECTAS)
# para pedirle al usuario que corrija la clave -- solo debe aparecer cuando
# SUNAT realmente la rechazo.
ERROR_CREDENCIALES_INCORRECTAS = "revisa usuario/clave"


def error_inicio_sesion(navegador: SunatWebNavigator) -> str:
    """
    Mensaje para un login fallido. Antes TODO fallo decia "revisa
    usuario/clave", aunque la causa fuera SUNAT lento o una pagina que no
    cargo -- el cliente terminaba cambiando una clave que estaba bien.
    """
    if navegador.credenciales_rechazadas:
        return f"SUNAT rechazo el usuario o la clave SOL ({ERROR_CREDENCIALES_INCORRECTAS})"
    return (
        "No se pudo completar el ingreso a SUNAT porque el portal no respondio como se esperaba "
        "(SUNAT no rechazo el usuario ni la clave). Intenta de nuevo en unos minutos."
    )


def consultar_buzon(
    ruc: str,
    usuario_sol: str,
    clave_sol: str,
    razon_social: str = "",
    headless: bool = True,
    limite_mensajes: int = 20,
    ids_conocidos: set | None = None,
    descargar_documentos: bool = True,
    leer_buzon_mensajes: bool = True,
    ids_conocidos_buzon_mensajes: set | None = None,
    leer_estado_contribuyente: bool = True,
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
    Antes se hacia en TODAS las consultas -- ahora el llamador (jobs.py)
    decide con leer_estado_contribuyente segun cuando se leyo por ultima
    vez (empresa.estado_contribuyente_verificado_en), para pagar ese costo
    extra solo una vez por dia en vez de en cada consulta individual. La
    condicion de domicilio NO tiene este costo (se lee del navbar que ya
    esta en pantalla justo despues del login, sin navegacion extra), asi
    que esa siempre se sigue leyendo en cada consulta.

    leer_estado_contribuyente: si es False, se salta el paso de la Ficha
    RUC por completo (resultado["estado_contribuyente"] queda en None,
    jobs.py interpreta eso como "sin cambios" y mantiene el valor guardado
    -- ver el chequeo `if estado_contribuyente and ...` en jobs.py).

    Si leer_buzon_mensajes=True (default), tambien entra a "Buzón
    Mensajes" -- bandeja SEPARADA de Notificaciones dentro del mismo
    Buzon Electronico, sin PDF adjunto en general (el contenido completo
    esta en el cuerpo del mensaje, ver adapter._leer_mensajes_buzon_mensajes
    y navegacion_buzon._navegar_a_buzon_mensajes). Un fallo leyendo esta
    bandeja NUNCA debe tumbar la consulta completa -- Notificaciones es
    lo principal, esto es informacion adicional.

    on_progreso: callback opcional, se llama con un string de etapa
    ("iniciando_sesion", "autenticando", "leyendo_estado", "abriendo_buzon",
    "leyendo_mensajes", "descargando_documentos", "leyendo_buzon_mensajes")
    en cada punto de avance -- mismo patron que
    generar_ficha_ruc_pdf(on_progreso=...), para que el llamador (jobs.py)
    pueda mostrar una barra de progreso real en el boton "Consultar" de
    cada empresa. Un fallo del callback en si nunca debe tumbar la
    consulta.

    Returns:
        dict: {
            "ok": bool,
            "mensajes": [{"fecha": str, "asunto": str}, ...],
            "documentos": {mensaje_id: ruta_local_del_pdf, ...},
            "mensajes_bandeja": [{"id_sunat", "fecha", "asunto", "leido",
                "contenido_texto"}, ...],  # Buzón Mensajes, ver arriba
            "razon_social_sunat": str | None,  # nombre real segun SUNAT
            "condicion_domicilio": str | None,  # Habido / No Habido / No Hallado
            "estado_contribuyente": str | None,  # Activo / Baja de Oficio / etc.
            "estado_contribuyente_verificado": bool,  # True si esta corrida SI intento leerlo (ver leer_estado_contribuyente)
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
            return {"ok": False, "mensajes": [], "documentos": {}, "mensajes_bandeja": [], "razon_social_sunat": None, "condicion_domicilio": None, "estado_contribuyente": None, "estado_contribuyente_verificado": False, "flujo_detectado": None, "error": "No se pudo iniciar el navegador"}

        _reportar("iniciando_sesion")
        navegador.driver.get(config.URL_SUNAT)
        time.sleep(3)

        _reportar("autenticando")
        if not navegador._hacer_clicks_sunat(empresa):
            return {"ok": False, "mensajes": [], "documentos": {}, "mensajes_bandeja": [], "razon_social_sunat": navegador.razon_social_detectada, "condicion_domicilio": navegador.condicion_domicilio_detectada, "estado_contribuyente": None, "estado_contribuyente_verificado": False, "flujo_detectado": navegador.flujo_detectado, "error": error_inicio_sesion(navegador), "credenciales_rechazadas": navegador.credenciales_rechazadas}

        # Se hace ANTES de navegar al Buzon (no despues) porque el
        # desplegable del nombre y el boton "Ver Ficha Ruc" viven en esta
        # misma pantalla del Menu SOL -- entrar al Buzon primero implicaria
        # tener que volver aca despues, mas navegacion y mas riesgo de
        # fallo. Un fallo leyendo esto NUNCA debe tumbar el resto de la
        # consulta (ver _leer_estado_contribuyente). Se salta por completo
        # si leer_estado_contribuyente=False (ya se verifico hoy, ver
        # jobs.py) -- ese es el ahorro real de los ~8-10s extra, la
        # condicion de domicilio de arriba no tiene este costo.
        _reportar("leyendo_estado")
        if leer_estado_contribuyente:
            navegador.estado_contribuyente_detectado = navegador._leer_estado_contribuyente()

        _reportar("abriendo_buzon")
        if not navegador._navegar_a_buzon_notificaciones():
            return {"ok": False, "mensajes": [], "documentos": {}, "mensajes_bandeja": [], "razon_social_sunat": navegador.razon_social_detectada, "condicion_domicilio": navegador.condicion_domicilio_detectada, "estado_contribuyente": navegador.estado_contribuyente_detectado, "estado_contribuyente_verificado": leer_estado_contribuyente, "flujo_detectado": navegador.flujo_detectado, "error": "Se inicio sesion pero no se pudo abrir el Buzon Electronico"}

        # Segundo chequeo del alert de listarAlertas (ver
        # _cerrar_alerta_si_aparece en navegacion_buzon.py): el de adentro de
        # _navegar_a_buzon_notificaciones espera un time.sleep(3) fijo tras
        # el clic, pero listarAlertas es una llamada async de la propia
        # pagina de SUNAT que a veces tarda mas que eso en fallar (confirmado
        # en produccion, 26/09: goteaba igual como "unexpected alert open" en
        # el siguiente comando de Selenium). Gratis si no hay alerta abierta.
        navegador._cerrar_alerta_si_aparece()

        _reportar("leyendo_mensajes")
        _esperar_lista_mensajes(navegador)
        mensajes = _leer_lista_mensajes(navegador, limite_mensajes)

        documentos = {}
        contenidos_texto_notificaciones = {}
        if descargar_documentos and ids_conocidos is not None:
            _reportar("descargando_documentos")
            try:
                documentos, contenidos_texto_notificaciones = _descargar_documentos_nuevos(navegador, ids_conocidos, limite_mensajes)
            except Exception as e:
                # Un fallo descargando documentos NUNCA debe tumbar la
                # consulta completa -- los mensajes ya se leyeron bien, eso
                # es lo importante. El documento se puede intentar de nuevo
                # en la proxima consulta (sigue sin estar en ids_conocidos
                # porque el mensaje en si si se guarda igual).
                logger.error(f"Error general descargando documentos para {ruc}: {e}")

        mensajes_bandeja = []
        if leer_buzon_mensajes:
            _reportar("leyendo_buzon_mensajes")
            try:
                mensajes_bandeja = _leer_mensajes_buzon_mensajes(
                    navegador, limite_mensajes, ids_conocidos_buzon_mensajes or set()
                )
            except Exception as e:
                # Mismo criterio que descargando_documentos arriba -- Buzón
                # Mensajes es informacion adicional, un fallo aca nunca debe
                # tumbar la consulta principal (Notificaciones ya se leyo bien).
                logger.error(f"Error leyendo Buzón Mensajes para {ruc}: {e}")

        return {
            "ok": True,
            "mensajes": mensajes,
            "documentos": documentos,
            "contenidos_texto_notificaciones": contenidos_texto_notificaciones,
            "mensajes_bandeja": mensajes_bandeja,
            "razon_social_sunat": navegador.razon_social_detectada,
            "condicion_domicilio": navegador.condicion_domicilio_detectada,
            "estado_contribuyente": navegador.estado_contribuyente_detectado,
            "estado_contribuyente_verificado": leer_estado_contribuyente,
            "flujo_detectado": navegador.flujo_detectado,
            "error": None,
        }

    except Exception as e:
        logger.error(f"Error consultando buzon de {ruc}: {e}")
        return {"ok": False, "mensajes": [], "documentos": {}, "mensajes_bandeja": [], "razon_social_sunat": None, "condicion_domicilio": None, "estado_contribuyente": None, "estado_contribuyente_verificado": False, "flujo_detectado": None, "error": str(e)}
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


def preparar_ingreso_directo_declaraciones(ruc: str = "", headless: bool = False) -> dict:
    """
    Igual que preparar_ingreso_directo (se detiene ANTES de escribir
    ninguna credencial, mismo motivo de seguridad), pero para un destino
    post-login distinto: "Mis Declaraciones y Pagos" en vez del Menu SOL
    clasico (Buzon).

    Es la MISMA pantalla de login SUNAT (oauth2/loginMenuSol) -- lo que
    cambia es el parametro `originalUrl`, que SUNAT arma segun por donde
    se entro. Confirmado con un diagnostico real (24/09): entrando por
    https://www.sunat.gob.pe/sol.html y disparando el mismo JS que usa el
    boton "Ingresar" de la tarjeta "Mis Declaraciones y Pagos"
    (declaraSimplificadaNueva(), definida en esa pagina), el originalUrl
    resultante apunta a cl-ti-itmenu2/AutenticaMenuInternetPlataforma.htm
    (la "Plataforma" nueva de declaraciones) en vez de
    cl-ti-itmenu/AutenticaMenuInternet.htm (el Menu SOL clasico que usa
    preparar_ingreso_directo). El resto del flujo (formulario oculto que
    se autoenvia en el navegador del usuario) es identico.

    Returns:
        dict: mismo formato que preparar_ingreso_directo.
    """
    vacio = {"ok": False, "accion_url": None, "state": None, "original_url": None, "lang": None, "error": None}

    navegador = SunatWebNavigator(empresa=None, headless=headless)
    try:
        if not navegador.initialize_browser():
            return {**vacio, "error": "No se pudo iniciar el navegador"}

        driver = navegador.driver
        driver.get("https://www.sunat.gob.pe/sol.html")
        ventana_original = driver.current_window_handle
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return typeof declaraSimplificadaNueva === 'function'")
        )
        driver.execute_script("declaraSimplificadaNueva()")

        ventanas_nuevas = []
        for _ in range(15):
            ventanas_nuevas = [w for w in driver.window_handles if w != ventana_original]
            if ventanas_nuevas:
                break
            time.sleep(1)
        if not ventanas_nuevas:
            return {**vacio, "error": "No se pudo llegar a la pantalla de login de 'Mis Declaraciones y Pagos'"}
        driver.switch_to.window(ventanas_nuevas[-1])

        WebDriverWait(driver, 15).until(lambda d: "loginMenuSol" in d.current_url or "j_security_check" in d.current_url)
        url_login = driver.current_url

        partes = urlparse(url_login)
        query = parse_qs(partes.query)
        state = query.get("state", [None])[0]
        original_url = query.get("originalUrl", [None])[0]
        lang = query.get("lang", ["es-PE"])[0]
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
        logger.error(f"Error preparando el ingreso directo a Declaraciones y Pagos para {ruc}: {e}")
        return {**vacio, "error": str(e)}
    finally:
        navegador.close_browser()


def preparar_ingreso_directo_renta_anual(ruc: str = "", headless: bool = False) -> dict:
    """
    Igual que preparar_ingreso_directo (se detiene ANTES de escribir
    ninguna credencial, mismo motivo de seguridad), pero para "DJ Anual"
    -- Declaracion Jurada Anual de Renta (Formulario 710 Empresas / 709
    Personas). Es un sistema DISTINTO de SOL/Buzon (dominio
    e-renta.sunat.gob.pe en vez de e-menu.sunat.gob.pe, con su propio
    client id de OAuth2) pero usa el MISMO mecanismo de login
    (oauth2/j_security_check, mismos nombres de campo: tipo/custom_ruc/
    j_username/j_password/state/originalUrl/lang) -- confirmado con un
    diagnostico real end-to-end (17/10/2026): entrar sin sesion a
    e-renta.sunat.gob.pe/loader/.../formularios?idFormulario=menu
    redirige solo (sin JS ni popup, a diferencia de Declaraciones y
    Pagos) a la pantalla de login con el originalUrl ya armado, y
    autoenviando el formulario oculto con eso se llega a la bienvenida
    real de "Renta Anual" ya logueado.

    Returns:
        dict: mismo formato que preparar_ingreso_directo.
    """
    vacio = {"ok": False, "accion_url": None, "state": None, "original_url": None, "lang": None, "error": None}

    navegador = SunatWebNavigator(empresa=None, headless=headless)
    try:
        if not navegador.initialize_browser():
            return {**vacio, "error": "No se pudo iniciar el navegador"}

        driver = navegador.driver
        driver.get(
            "https://e-renta.sunat.gob.pe/loader/recaudaciontributaria/declaracionpago/formularios?idFormulario=menu"
        )
        WebDriverWait(driver, 15).until(
            lambda d: "j_security_check" in d.current_url or "oauth2/login" in d.current_url
        )
        url_login = driver.current_url

        partes = urlparse(url_login)
        query = parse_qs(partes.query)
        state = query.get("state", [None])[0]
        original_url = query.get("originalUrl", [None])[0]
        lang = query.get("lang", ["es-PE"])[0]
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
        logger.error(f"Error preparando el ingreso directo a DJ Anual para {ruc}: {e}")
        return {**vacio, "error": str(e)}
    finally:
        navegador.close_browser()


def _esperar_lista_mensajes(navegador, timeout: int = 20) -> bool:
    """
    Espera a que el listado del Buzon (los <small class="fecPublica">) aparezca,
    arriba o dentro de algun iframe de primer nivel. Confirmado en produccion
    (Misky Sonko, 23/10/2026): tras el alert de listarAlertas el listado se
    leyo en menos de 1 s, todavia vacio, y la corrida no vio ningun mensaje
    (ni reintento los PDF que faltaban). Un buzon realmente vacio solo cuesta
    esta espera. Deja el driver en default_content; _escanear_mensajes se
    ubica solo en el iframe correcto.
    """
    driver = navegador.driver
    limite = time.time() + timeout
    while time.time() < limite:
        navegador._cerrar_alerta_si_aparece()
        try:
            driver.switch_to.default_content()
            if driver.find_elements(By.CLASS_NAME, "fecPublica"):
                return True
            for iframe in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    driver.switch_to.frame(iframe)
                    hay = bool(driver.find_elements(By.CLASS_NAME, "fecPublica"))
                finally:
                    driver.switch_to.default_content()
                if hay:
                    return True
        except Exception as e:
            logger.debug(f"Esperando el listado del Buzon: {e}")
        time.sleep(1)
    logger.warning(f"El listado del Buzon no aparecio en {timeout} s (buzon vacio o SUNAT lento)")
    return False


def _escanear_mensajes(navegador, limite):
    """
    Escanea el listado visible en el Buzon Electronico y devuelve, por cada
    mensaje, su fecha/asunto (para guardar en la base) y el elemento <a>
    clickeable (para poder entrar a descargar su documento). Se separa de
    _leer_lista_mensajes porque ese solo necesita texto -- aca ademas
    necesitamos la referencia al elemento del DOM.

    IMPORTANTE (confirmado en produccion, 24/09): el listado de mensajes se
    carga DENTRO de un iframe -- segun por donde termino navegando
    _navegar_a_buzon_notificaciones() (y sobre todo en cuentas donde SUNAT
    mostro el modal extra de "Flujo 1" tras el login), el driver a veces
    queda posicionado en el contexto de arriba (default_content) en vez de
    dentro de ese iframe. La pagina se ve perfecta a simple vista (una
    captura de pantalla lo confirma) pero find_elements busca en el
    contexto EQUIVOCADO y no encuentra nada -- una empresa con mensajes
    reales quedaba guardada como si el buzon estuviera vacio. Por eso se
    busca primero en default_content, y si no aparece nada ahi, se recorre
    cada iframe de primer nivel hasta encontrar el que sí tiene los
    mensajes, dejando el driver posicionado ahi antes de escanear.
    """
    if not navegador.driver.find_elements(By.CLASS_NAME, "fecPublica"):
        navegador.driver.switch_to.default_content()
        for iframe in navegador.driver.find_elements(By.TAG_NAME, "iframe"):
            try:
                navegador.driver.switch_to.frame(iframe)
            except Exception:
                navegador.driver.switch_to.default_content()
                continue
            if navegador.driver.find_elements(By.CLASS_NAME, "fecPublica"):
                break
            navegador.driver.switch_to.default_content()

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


# Cuantos mensajes NUEVOS de Buzón Mensajes se abren (para leer su
# contenido) en una sola corrida -- cada uno cuesta varios segundos
# (clic + esperar el iframe interno), asi que un limite bajo evita que
# la primera consulta de una empresa con mucho historial se alargue
# indefinidamente. El resto queda pendiente para la proxima consulta
# (mismo criterio que MAX_DESCARGAS_POR_CORRIDA arriba).
MAX_MENSAJES_NUEVOS_BUZON_MENSAJES_POR_CORRIDA = int(
    os.environ.get("SUNAT_MAX_MENSAJES_BUZON_MENSAJES_POR_CORRIDA", 15)
)


def mensaje_id_buzon_mensajes(id_sunat: str) -> str:
    """
    Identificador estable de un mensaje de Buzón Mensajes -- a diferencia
    de Notificaciones (que solo tiene fecha+asunto y necesita un hash,
    ver mensaje_id() arriba), esta bandeja SI trae un id nativo de SUNAT
    (el atributo id del <li> de cada mensaje en el listado, confirmado en
    vivo 25/09/2026) -- se usa directo, con un prefijo para que este
    espacio de nombres nunca choque por casualidad con un hash de
    Notificaciones.
    """
    return f"bm-{id_sunat}"


def _escanear_mensajes_buzon_mensajes(navegador, limite):
    """
    Escanea el listado de "Buzón Mensajes" (bandeja separada de
    Notificaciones, ver navegacion_buzon._navegar_a_buzon_mensajes).
    Estructura real confirmada en vivo (25/09/2026): cada mensaje es
    <li id="ID_SUNAT">...<a class="linkMensaje">ASUNTO</a>...
    <small class="fecPublica">FECHA</small>...
    <input id="idLeido" value="0|1">...</li>, dentro de
    <ul id="listaMensajes">.
    """
    def buscar_enlaces(driver):
        elementos = driver.find_elements(By.CLASS_NAME, "linkMensaje")
        return elementos or None

    encontrados = navegador._buscar_en_default_y_iframes(buscar_enlaces)
    if not encontrados:
        return []

    resultado = []
    vistos = set()
    for enlace in encontrados[:limite]:
        try:
            li_padre = enlace.find_element(By.XPATH, "./ancestor::li")
            id_sunat = li_padre.get_attribute("id") or ""
            if not id_sunat or id_sunat in vistos:
                continue
            vistos.add(id_sunat)

            asunto = enlace.text.strip() or "(sin asunto)"

            fecha = ""
            try:
                fecha = li_padre.find_element(By.CLASS_NAME, "fecPublica").text.strip()
            except Exception:
                pass

            leido = False
            try:
                leido = li_padre.find_element(By.ID, "idLeido").get_attribute("value") == "1"
            except Exception:
                pass

            resultado.append({
                "id_sunat": id_sunat, "fecha": fecha, "asunto": asunto,
                "leido": leido, "elemento": enlace,
            })
        except Exception:
            continue

    return resultado


def _leer_contenido_texto_mensaje(navegador, timeout=8):
    """
    Despues de hacer clic en un mensaje de Buzón Mensajes, el contenido
    real se carga en un iframe anidado <iframe id="contenedorMensaje">
    (confirmado en vivo 25/09/2026) -- el body.text "de arriba" solo trae
    la lista de mensajes mas un texto de respaldo ("El browser no soporta
    IFRAMES..."), asi que hay que cambiar de contexto explicitamente.

    Devuelve el texto o None si no se pudo leer -- p.ej. algunos mensajes
    de esta bandeja (caso minoritario, confirmado en vivo con el icono de
    clip en la lista) traen un adjunto en vez de contenido en linea y no
    siempre usan este mismo iframe; no vale la pena tumbar la consulta
    por eso, se guarda el mensaje igual, solo sin contenido_texto.
    """
    def buscar_iframe(driver):
        try:
            return driver.find_element(By.ID, "contenedorMensaje")
        except Exception:
            return None

    iframe_el = navegador._buscar_en_default_y_iframes(buscar_iframe)
    if iframe_el is None:
        return None

    try:
        navegador.driver.switch_to.frame(iframe_el)
        time.sleep(1)
        texto = navegador.driver.find_element(By.TAG_NAME, "body").text.strip()
        return texto or None
    except Exception as e:
        logger.warning(f"No se pudo leer el contenido del iframe 'contenedorMensaje': {e}")
        return None
    finally:
        navegador.driver.switch_to.default_content()


def _leer_mensajes_buzon_mensajes(navegador, limite, ids_conocidos: set) -> list[dict]:
    """
    Navega a Buzón Mensajes, y para cada mensaje NUEVO (id_sunat no esta
    en ids_conocidos) hace clic y extrae su contenido de texto completo.
    Los mensajes ya conocidos NO se vuelven a abrir -- ya se guardaron
    con su contenido en una corrida anterior.

    Vuelve a escanear la lista COMPLETA despues de cada mensaje procesado
    (en vez de reusar referencias de elementos ya usadas una vez) --
    mismo motivo y mismo patron que _descargar_documentos_nuevos: entrar
    al iframe anidado del contenido y volver a default_content dentro de
    _leer_contenido_texto_mensaje puede dejar obsoletas las referencias
    del DOM que Selenium ya tenia para el resto de la lista.

    Devuelve una lista de dicts: {"id_sunat", "fecha", "asunto", "leido",
    "contenido_texto"} -- contenido_texto puede ser None (ver docstring
    de _leer_contenido_texto_mensaje).
    """
    if not navegador._navegar_a_buzon_mensajes():
        logger.warning("No se pudo entrar a Buzón Mensajes -- se omite esta bandeja en esta consulta.")
        return []

    resultado = []
    intentados = set()

    while len(resultado) < MAX_MENSAJES_NUEVOS_BUZON_MENSAJES_POR_CORRIDA:
        candidatos = _escanear_mensajes_buzon_mensajes(navegador, limite)

        objetivo = None
        for c in candidatos:
            if mensaje_id_buzon_mensajes(c["id_sunat"]) in ids_conocidos or c["id_sunat"] in intentados:
                continue
            objetivo = c
            break

        if objetivo is None:
            break  # no quedan mensajes nuevos por leer

        intentados.add(objetivo["id_sunat"])
        logger.info(f"Leyendo contenido del mensaje nuevo de Buzón Mensajes: '{objetivo['asunto']}'")

        contenido_texto = None
        try:
            try:
                objetivo["elemento"].click()
            except Exception:
                navegador.driver.execute_script("arguments[0].click();", objetivo["elemento"])
            time.sleep(3)
            contenido_texto = _leer_contenido_texto_mensaje(navegador)
        except Exception as e:
            logger.warning(f"No se pudo abrir el mensaje '{objetivo['asunto']}' de Buzón Mensajes: {e}")

        resultado.append({
            "id_sunat": objetivo["id_sunat"],
            "fecha": objetivo["fecha"],
            "asunto": objetivo["asunto"],
            "leido": objetivo["leido"],
            "contenido_texto": contenido_texto,
        })

    return resultado


def _descargar_documentos_nuevos(navegador, ids_conocidos: set, limite: int) -> tuple[dict, dict]:
    """
    Descarga el documento (PDF) de cada mensaje que no este en
    ids_conocidos, reutilizando _descargar_documento_constancia() -- el
    metodo ya probado en produccion por la automatizacion original.

    Vuelve a escanear la lista de mensajes despues de cada descarga (en vez
    de reusar referencias de elementos ya usadas una vez) porque hacer clic
    en un mensaje y volver atras puede dejar obsoletas las referencias del
    DOM que Selenium ya tenia -- es un poco mas lento pero mucho mas
    confiable que tratar de "refrescar" las referencias viejas.

    Respaldo de texto (confirmado en produccion, 2026-09-25): no TODOS los
    mensajes de Buzón Notificaciones traen un PDF -- algunos tipos (ej.
    "NOTIFICACION DE LA DECLARACION") solo traen un enlace generico de
    contacto dentro del iframe "contenedorMensaje", sin ningun link
    constancia_/goArchivoDescarga. Antes, esos mensajes quedaban guardados
    sin PDF Y sin ninguna otra forma de verlos -- invisibles para siempre
    en el tablero, reintentados sin exito en cada consulta futura. Como
    _descargar_documento_constancia() siempre deja al driver en
    default_content antes de volver (exito o no), es seguro usar el mismo
    _leer_contenido_texto_mensaje() que ya usa Buzón Mensajes como
    respaldo cuando no aparecio ningun PDF -- mismo iframe, confirmado con
    el log real de esa corrida.

    Returns:
        tuple[dict, dict]:
          - {mensaje_id: ruta_local_del_pdf_descargado}
          - {mensaje_id: contenido_texto_de_respaldo} (solo para mensajes
            sin PDF donde se pudo leer el iframe igual)
    """
    descargados = {}
    contenidos_texto_respaldo = {}
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

            if mid not in descargados:
                try:
                    texto_respaldo = _leer_contenido_texto_mensaje(navegador)
                    if texto_respaldo:
                        contenidos_texto_respaldo[mid] = texto_respaldo
                        logger.info(f"Contenido de texto de respaldo capturado (sin PDF) para '{msg['asunto']}'")
                except Exception as e:
                    logger.warning(f"No se pudo leer contenido de texto de respaldo para '{msg['asunto']}': {e}")
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

    return descargados, contenidos_texto_respaldo


def generar_ficha_ruc_pdf(
    ruc: str,
    usuario_sol: str,
    clave_sol: str,
    razon_social: str = "",
    headless: bool = True,
    on_progreso=None,
    con_qr: bool = False,
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

    con_qr: si es False (default), genera el documento de siempre -- la
    "CIR - Constancia de Informacion Registrada" completa, via
    Page.printToPDF (logica verificada con un diagnostico real contra
    produccion, diagnostico_ficha_ruc.py):
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

    Si con_qr es True, genera el "Reporte de Ficha RUC" -- un documento
    DISTINTO, firmado y con un codigo QR de verificacion en la ultima
    pagina (confirmado en produccion, 24/09: valida contra una URL propia
    de SUNAT). Se llega por un boton separado, "Descargar Ficha RUC", en
    la misma pantalla de edicion de la Ficha RUC -- abre una pantalla de
    aviso con botones "Enviar por Correo" / "Descargar" / "Cancelar"; se
    usa "Descargar" (no necesita correo) y SUNAT dispara una descarga de
    archivo real en vez de abrir una pestaña nueva. OJO: SUNAT limita esto
    a 3 generaciones por dia POR EMPRESA -- a partir de la 4ta, devuelve
    en silencio el ultimo reporte ya generado (nunca un error). El
    llamador (jobs.py) es responsable de avisarle al usuario ANTES de
    llegar a ese limite, contando FichaRucJob.con_qr=True de hoy.

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
            return {"ok": False, "pdf_bytes": None, "error": error_inicio_sesion(navegador), "credenciales_rechazadas": navegador.credenciales_rechazadas}

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
        if con_qr:
            _reportar("generando_pdf")
            try:
                boton_descargar_ficha = WebDriverWait(driver, 8).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@value='Descargar Ficha RUC']"))
                )
            except Exception as e:
                return {"ok": False, "pdf_bytes": None, "error": f"No se encontro el boton 'Descargar Ficha RUC': {e}"}
            try:
                boton_descargar_ficha.click()
            except Exception:
                driver.execute_script("arguments[0].click();", boton_descargar_ficha)
            time.sleep(3)

            # Pantalla de aviso (max 3 reportes/dia) con "Enviar por Correo"
            # (btnCorreo) / "Descargar" (btnAceptar) / "Cancelar"
            # (btnCancelar) -- se usa Descargar, no necesita correo y SUNAT
            # dispara una descarga de archivo real (no una pestaña nueva).
            try:
                boton_aceptar = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "btnAceptar"))
                )
            except Exception as e:
                return {"ok": False, "pdf_bytes": None, "error": f"No aparecio la pantalla de descarga del Reporte de Ficha RUC: {e}"}

            archivos_antes = set(os.listdir(navegador.download_dir))
            try:
                boton_aceptar.click()
            except Exception:
                driver.execute_script("arguments[0].click();", boton_aceptar)

            if not navegador._esperar_descarga(timeout=30):
                return {"ok": False, "pdf_bytes": None, "error": "El Reporte de Ficha RUC (con QR) no termino de descargarse a tiempo"}

            archivos_nuevos = [
                f for f in (set(os.listdir(navegador.download_dir)) - archivos_antes)
                if f.lower().endswith(".pdf")
            ]
            if not archivos_nuevos:
                return {"ok": False, "pdf_bytes": None, "error": "La descarga del Reporte de Ficha RUC no dejo ningun PDF nuevo"}
            ruta_pdf = os.path.join(navegador.download_dir, archivos_nuevos[0])
            with open(ruta_pdf, "rb") as f:
                pdf_bytes = f.read()

            if not pdf_bytes:
                return {"ok": False, "pdf_bytes": None, "error": "El Reporte de Ficha RUC descargado quedo vacio"}

            logger.info(f"Reporte de Ficha RUC (con QR) generado correctamente para {ruc} ({len(pdf_bytes)} bytes)")
            return {"ok": True, "pdf_bytes": pdf_bytes, "error": None}

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


def _buscar_en_algun_frame(driver, by, valor, timeout=20):
    """
    Busca un elemento primero en default_content y, si no aparece, lo
    busca dentro de cada iframe de primer nivel (mismo patron que
    _escanear_mensajes en adapter.py) -- el contenido de Menu SOL se carga
    en iframes de forma inconsistente segun por donde se navego, asi que
    no alcanza con asumir un solo contexto fijo. Reintenta durante
    `timeout` segundos (confirmado en produccion, 24/09: esta pantalla en
    particular a veces tarda en terminar de cargar via AJAX, sobre todo
    en cuentas que pasaron por el modal "Flujo 1" post-login -- un solo
    intento sin espera podia no encontrar nada todavia). Devuelve el
    elemento encontrado (dejando al driver posicionado en el contexto
    correcto) o None si no aparece en ningun lado dentro del timeout.
    """
    inicio = time.time()
    while time.time() - inicio < timeout:
        driver.switch_to.default_content()
        try:
            return driver.find_element(by, valor)
        except Exception:
            pass
        for iframe in driver.find_elements(By.TAG_NAME, "iframe"):
            driver.switch_to.default_content()
            try:
                driver.switch_to.frame(iframe)
                return driver.find_element(by, valor)
            except Exception:
                continue
        driver.switch_to.default_content()
        time.sleep(1)
    return None


def generar_reporte_tributario_terceros(
    ruc: str,
    usuario_sol: str,
    clave_sol: str,
    correo_destino: str,
    razon_social: str = "",
    headless: bool = True,
    on_progreso=None,
) -> dict:
    """
    Inicia sesion en SUNAT SOL y solicita el "Reporte Tributario para
    Terceros" (informacion RESERVADA segun el Art. 85 del Codigo
    Tributario -- a diferencia de la Ficha RUC, que es publica) al correo
    indicado. A diferencia de generar_ficha_ruc_pdf, esta funcion NO
    descarga ningun PDF: SUNAT genera y envia el reporte por su cuenta:
    aca solo se entra, se acepta el aviso legal, y se pide el envio.

    Ruta confirmada con un diagnostico real (24/09): Menu SOL -> "Mi RUC y
    Otros Registros" -> "Envio Reporte Tributario" -> "Reporte" ->
    "Reporte Tributario para Terceros" (codigo de menu 10.11.1.1.1) --
    NO confundir con "Reporte Tributario y Aduanero" (10.4), una opcion
    DISTINTA con su propio limite (1 por dia, hasta 1 hora de espera) que
    no es la que se automatiza aca.

    OJO: SUNAT limita esto a 3 solicitudes por dia POR EMPRESA -- a partir
    de la 4ta, reenvia la ultima ya generada sin avisar (mismo aviso que
    en el "Reporte de Ficha RUC" con QR). El llamador (jobs.py) es
    responsable de avisarle al usuario ANTES de llegar a ese limite.

    Returns:
        dict: {"ok": bool, "error": str | None}
    """

    def _reportar(etapa: str):
        if on_progreso is None:
            return
        try:
            on_progreso(etapa)
        except Exception as e:
            logger.warning(f"El callback de progreso fallo (no es grave, se sigue igual): {e}")

    empresa = {"ruc": ruc, "usuario": usuario_sol, "clave": clave_sol, "razon_social": razon_social}
    navegador = SunatWebNavigator(empresa=empresa, headless=headless)
    # Se activa justo antes del clic en "Enviar" (mas abajo) -- a partir de
    # ahi SUNAT pudo haber procesado la solicitud (cuenta contra el limite
    # de 3 por dia por empresa) aunque despues fallara algun paso cosmetico
    # (ej. leer el mensaje de confirmacion). El llamador (jobs.py) usa esto
    # para decidir si es seguro reintentar toda la funcion desde cero.
    solicitud_pudo_haberse_enviado = False
    try:
        if not navegador.initialize_browser():
            return {"ok": False, "error": "No se pudo iniciar el navegador", "solicitud_pudo_haberse_enviado": False}

        _reportar("iniciando_sesion")
        navegador.driver.get(config.URL_SUNAT)
        time.sleep(3)

        _reportar("autenticando")
        if not navegador._hacer_clicks_sunat(empresa):
            return {"ok": False, "error": error_inicio_sesion(navegador), "solicitud_pudo_haberse_enviado": False, "credenciales_rechazadas": navegador.credenciales_rechazadas}

        driver = navegador.driver
        ventana_original = driver.current_window_handle

        _reportar("abriendo_reporte")
        try:
            for elid in ("nivel2_10_11", "nivel3_10_11_1", "nivel4_10_11_1_1_1"):
                el = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, elid)))
                try:
                    el.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", el)
                time.sleep(2)
                logger.info(f"Reporte Tributario para Terceros: clic en {elid} hecho")
        except Exception as e:
            return {"ok": False, "error": f"No se pudo abrir 'Reporte Tributario para Terceros' en el menu de SUNAT: {e}", "solicitud_pudo_haberse_enviado": False}
        # El clic en el 3er nivel del menu abre una pestaña nueva con el
        # aviso legal (informacion reservada, Art. 85) -- cambiarse a ella.
        # OJO (confirmado en produccion, 24/09): "cualquier ventana que no
        # sea ventana_original" no alcanza -- puede haber OTRAS ventanas
        # sueltas de mas temprano en el login (se confirmo una con titulo
        # "SUNAT SOL Operaciones en Línea" / sol.html, ajena a este
        # reporte). Se busca especificamente la ventana cuyo titulo
        # mencione "TERCEROS", reintentando por si tarda en aparecer.
        ventana_reporte = None
        for _ in range(15):
            for handle in driver.window_handles:
                driver.switch_to.window(handle)
                if "TERCEROS" in driver.title.upper():
                    ventana_reporte = handle
                    break
            if ventana_reporte:
                break
            time.sleep(1)
        logger.info(f"Reporte Tributario para Terceros: ventana del reporte encontrada = {ventana_reporte is not None}")
        if ventana_reporte:
            driver.switch_to.window(ventana_reporte)
        time.sleep(2)

        _reportar("aceptando_aviso")
        checkbox_acepto = _buscar_en_algun_frame(driver, By.ID, "chkAceptar")
        if checkbox_acepto is None:
            logger.warning(f"Reporte Tributario para Terceros: no se encontro chkAceptar. Titulo actual: {driver.title!r}, URL: {driver.current_url!r}")
            return {"ok": False, "error": "No aparecio el aviso legal ('Acepto') del Reporte Tributario para Terceros", "solicitud_pudo_haberse_enviado": False}
        # El checkbox real de SUNAT en esta pantalla no acepta un clic
        # nativo (ElementNotInteractableException, confirmado en
        # produccion -- probablemente esta detras de un overlay/estilo
        # personalizado) -- se hace por JS, disparando el evento "change"
        # a mano para que el JS de la pagina que habilita el boton
        # "Acepto" (habilitarIngreso()) se entere igual.
        driver.execute_script(
            "arguments[0].click(); arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
            checkbox_acepto,
        )
        time.sleep(1)
        try:
            boton_acepto = driver.find_element(By.ID, "btnAceptar")
            driver.execute_script("arguments[0].click();", boton_acepto)
        except Exception as e:
            return {"ok": False, "error": f"No se pudo continuar despues de aceptar el aviso legal: {e}", "solicitud_pudo_haberse_enviado": False}
        time.sleep(4)

        _reportar("enviando_correo")
        # El Menu SOL tiene OTRO input oculto con id="txtCorreo" (formulario
        # de datos de contacto) y, desde que SUNAT abre este reporte en un
        # iframe y no en pestaña aparte, una busqueda directa encontraba ese
        # primero: se llenaba el campo equivocado y SUNAT respondia
        # "INFORMACION DE CORREO INCOMPLETA". Se ubica primero btnCorreo
        # (unico de este formulario) y se toma el txtCorreo de ese mismo frame.
        boton_enviar = _buscar_en_algun_frame(driver, By.ID, "btnCorreo")
        if boton_enviar is None:
            return {"ok": False, "error": "No se encontro el boton 'Enviar' del Reporte Tributario para Terceros", "solicitud_pudo_haberse_enviado": False}
        try:
            campo_correo = driver.find_element(By.ID, "txtCorreo")
        except Exception:
            return {"ok": False, "error": "No aparecio el campo de correo del Reporte Tributario para Terceros", "solicitud_pudo_haberse_enviado": False}
        try:
            campo_correo.clear()
            campo_correo.send_keys(correo_destino)
        except Exception:
            # Mismo problema que el checkbox de arriba -- este campo
            # tampoco acepta interaccion nativa en esta pantalla en
            # particular. Se setea el value por JS y se disparan los
            # eventos que el JS de la pagina espera para reconocer el
            # cambio (input + change, React/Vue suelen escuchar "input").
            driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                campo_correo,
                correo_destino,
            )
        time.sleep(1)
        try:
            boton_enviar.click()
        except Exception:
            driver.execute_script("arguments[0].click();", boton_enviar)
        # A partir de aca SUNAT pudo haber recibido y procesado la
        # solicitud (cuenta contra el limite de 3/dia) aunque algo
        # cosmetico falle despues (ej. leer el texto de confirmacion).
        solicitud_pudo_haberse_enviado = True
        # La pagina valida tokens anti-robot (Cloudflare Turnstile /
        # reCAPTCHA v3, agregados por SUNAT en 2026) antes de enviar, asi que
        # la respuesta puede tardar: se espera la confirmacion o el panel de
        # error (#msgErrorCorreo) en vez de mirar una sola vez a ciegas.
        error_sunat = ""
        for _ in range(20):
            time.sleep(1)
            texto = driver.find_element(By.TAG_NAME, "body").text
            if "se está procesando" in texto or "se esta procesando" in texto:
                break
            error_sunat = driver.execute_script(
                "var e=document.getElementById('msgErrorCorreo');"
                "return (e && !e.classList.contains('hidden')) ? e.innerText.replace('×','').replace('Close','').trim() : '';"
            )
            if error_sunat:
                break

        # SUNAT confirma con un mensaje reconocible (confirmado con una
        # captura real, 24/09): "El reporte solicitado se esta
        # procesando. Terminada dicha accion el mismo estara en la
        # bandeja de correo ingresada." -- se busca ese texto para
        # devolver un "ok" con confianza real, no solo "no revento".
        #
        # Bug real (reportado por el usuario, 2026-10-16): esta funcion
        # calculaba "confirmado" y lo logueaba, pero el return de abajo
        # SIEMPRE devolvia ok=True sin mirarlo -- el job quedaba marcado
        # "completado" en el tablero aunque SUNAT nunca hubiera mostrado el
        # mensaje de confirmacion (y el correo real nunca llegara). Ahora
        # "ok" refleja "confirmado" de verdad; si no se confirma, se marca
        # como error explicito (solicitud_pudo_haberse_enviado=True evita
        # que jobs.py reintente a ciegas y gaste otra de las 3 solicitudes
        # diarias que permite SUNAT).
        texto_pantalla = driver.find_element(By.TAG_NAME, "body").text
        confirmado = "se está procesando" in texto_pantalla or "se esta procesando" in texto_pantalla
        logger.info(f"Reporte Tributario para Terceros solicitado para {ruc} -> {correo_destino} (confirmado={confirmado})")
        if not confirmado and error_sunat:
            logger.warning(f"SUNAT rechazo el envio del Reporte Tributario para Terceros: {error_sunat!r}")
            return {
                "ok": False,
                "error": f"SUNAT rechazo el envio del reporte: {error_sunat}",
                "solicitud_pudo_haberse_enviado": True,
            }
        # enviarCorreo() de SUNAT no envia el formulario hasta obtener un token
        # de Cloudflare Turnstile; con un navegador automatizado Turnstile pide
        # marcar "Verify you are human" y el token nunca llega. No se intenta
        # eludir esa verificacion: el envio queda en manos del usuario.
        turnstile_pendiente = driver.execute_script(
            "var t=document.querySelector('[name=\"cf-turnstile-response\"]'); return !!t && !t.value;"
        )
        if not confirmado and turnstile_pendiente:
            logger.warning(f"Reporte Tributario para Terceros de {ruc}: SUNAT exige verificacion humana (Cloudflare Turnstile)")
            return {
                "ok": False,
                "error": (
                    "SUNAT ahora exige una verificacion humana (\"Verify you are human\") para enviar el "
                    "Reporte Tributario para Terceros, asi que no se puede automatizar. No se envio nada ni "
                    "se gasto ninguno de los 3 envios del dia: usa el boton \"Ir a SUNAT\" de esta empresa y "
                    "solicitalo en Mi RUC y Otros Registros > Envio Reporte Tributario > Reporte Tributario para Terceros."
                ),
                "solicitud_pudo_haberse_enviado": False,
                "verificacion_humana": True,
            }
        if not confirmado:
            logger.warning(f"No se encontro el mensaje de confirmacion esperado. Texto en pantalla: {texto_pantalla[-600:]!r}")
            navegador._guardar_captura_error("reporte_tributario_sin_confirmacion")
            return {
                "ok": False,
                "error": (
                    "Se envio la solicitud pero SUNAT no mostro el mensaje de confirmacion esperado "
                    "-- es posible que el reporte NO llegue al correo indicado. Revisa el correo de "
                    "destino antes de reintentar (cada intento cuenta contra el limite de 3 por dia)."
                ),
                "solicitud_pudo_haberse_enviado": True,
            }
        return {"ok": True, "error": None, "solicitud_pudo_haberse_enviado": True}

    except Exception as e:
        logger.error(f"Error solicitando el Reporte Tributario para Terceros de {ruc}: {e}")
        return {"ok": False, "error": str(e), "solicitud_pudo_haberse_enviado": solicitud_pudo_haberse_enviado}
    finally:
        navegador.close_browser()


def _abrir_opcion_menu_sol(navegador: SunatWebNavigator, ids_menu, codigo_opcion: str, nombre_opcion: str) -> str | None:
    """
    Recorre el Menu SOL clic por clic (ids_menu, del nivel 1 al 4) y deja el
    driver DENTRO del iframe donde SUNAT carga esa opcion (su src lleva
    code=<codigo_opcion>). Devuelve None si quedo lista, o el mensaje de
    error para el usuario.

    El alert de "listarAlertas" (error 500 propio de SUNAT al cargar el Menu
    SOL, ver _cerrar_alerta_si_aparece) bloquea cualquier comando de
    Selenium mientras siga abierto, asi que se descarta antes de cada clic.
    """
    driver = navegador.driver
    driver.switch_to.default_content()
    time.sleep(2)
    navegador._cerrar_alerta_si_aparece()
    for elid in ids_menu:
        navegador._cerrar_alerta_si_aparece()
        elementos = driver.find_elements(By.ID, elid)
        if not elementos:
            return f"El Menu SOL de esta empresa no muestra {nombre_opcion}"
        driver.execute_script("arguments[0].click();", elementos[0])
        time.sleep(2)

    for _ in range(30):
        navegador._cerrar_alerta_si_aparece()
        frame = next(
            (f for f in driver.find_elements(By.TAG_NAME, "iframe")
             if f"code={codigo_opcion}" in (f.get_attribute("src") or "")),
            None,
        )
        if frame is not None:
            driver.switch_to.frame(frame)
            return None
        time.sleep(1)
    return f"SUNAT no abrio la pantalla de {nombre_opcion}"


# Codigos de libro que usa la API interna del SIRE (los mismos que pide la
# pantalla de Gestion de Ventas / Gestion de Compras de SUNAT).
LIBROS_SIRE = {"RVIE": "140000", "RCE": "080000"}
_URL_PERIODOS_SIRE = "https://api-sire.sunat.gob.pe/v1/contribuyente/migeigv/libros/rvierce/padron/web/omisos/{cod}/periodos"
# Menu SOL: SIRE > Registros Electronicos > Registro de Ventas e Ingresos > Gestion de Ventas e Ingresos.
_MENU_GESTION_VENTAS_SIRE = ("nivel1_60", "nivel2_60_2", "nivel3_60_2_1", "nivel4_60_2_1_1_1")


def consultar_estado_sire(
    ruc: str,
    usuario_sol: str,
    clave_sol: str,
    razon_social: str = "",
    headless: bool = True,
    on_progreso=None,
) -> dict:
    """
    SOLO LECTURA: abre "Gestion de Ventas e Ingresos Electronicos" del SIRE
    (para que SUNAT emita el token de la app en sessionStorage) y pide, con
    ese mismo token, los listados de periodos que la propia pantalla usa para
    su selector de Periodo -- uno para el RVIE y otro para el RCE. Asi se
    obtienen TODOS los periodos de todos los anios en una sola sesion, sin
    tocar ningun boton del SIRE (Aceptar propuesta, Generar, etc.).

    Returns:
        {"ok": bool, "error": str | None,
         "libros": {"RVIE": [{"periodo": "2026-09", "cod_estado": "02", "des_estado": "Presentado"}, ...],
                    "RCE": [...]}}
    """
    def _reportar(etapa: str):
        if on_progreso is None:
            return
        try:
            on_progreso(etapa)
        except Exception as e:
            logger.warning(f"El callback de progreso fallo (no es grave, se sigue igual): {e}")

    empresa = {"ruc": ruc, "usuario": usuario_sol, "clave": clave_sol, "razon_social": razon_social}
    navegador = SunatWebNavigator(empresa=empresa, headless=headless)
    try:
        if not navegador.initialize_browser():
            return {"ok": False, "error": "No se pudo iniciar el navegador", "libros": {}}

        _reportar("iniciando_sesion")
        navegador.driver.get(config.URL_SUNAT)
        time.sleep(3)

        _reportar("autenticando")
        if not navegador._hacer_clicks_sunat(empresa):
            return {"ok": False, "error": error_inicio_sesion(navegador), "libros": {}, "credenciales_rechazadas": navegador.credenciales_rechazadas}

        driver = navegador.driver
        driver.switch_to.default_content()

        _reportar("abriendo_sire")
        error_menu = _abrir_opcion_menu_sol(
            navegador, _MENU_GESTION_VENTAS_SIRE, "60.2.1.1.1", "el SIRE (Registros Electronicos)"
        )
        if error_menu:
            return {"ok": False, "error": error_menu, "libros": {}}

        try:
            WebDriverWait(driver, 45).until(
                lambda d: d.execute_script("return !!sessionStorage.getItem('SUNAT.token')")
            )
        except Exception:
            navegador._guardar_captura_error("sire_sin_token")
            return {"ok": False, "error": "El SIRE no termino de cargar (sin sesion de la aplicacion)", "libros": {}}

        _reportar("leyendo_periodos")
        driver.set_script_timeout(60)
        libros = {}
        for libro, cod in LIBROS_SIRE.items():
            status, cuerpo = driver.execute_async_script(
                """
                var done = arguments[arguments.length - 1];
                fetch(arguments[0], {headers: {
                    'Authorization': 'Bearer ' + sessionStorage.getItem('SUNAT.token'),
                    'Accept': 'application/json'}})
                  .then(function (r) { return r.text().then(function (t) { done([r.status, t]); }); })
                  .catch(function (e) { done([0, String(e)]); });
                """,
                _URL_PERIODOS_SIRE.format(cod=cod),
            )
            if status != 200:
                return {"ok": False, "error": f"SUNAT respondio HTTP {status} al pedir los periodos del {libro}", "libros": {}}
            periodos = []
            for anio in json.loads(cuerpo or "[]"):
                for p in anio.get("lisPeriodos") or []:
                    per = str(p.get("perTributario") or "")
                    if len(per) != 6:
                        continue
                    periodos.append({
                        "periodo": f"{per[:4]}-{per[4:]}",
                        "cod_estado": str(p.get("codEstado") or ""),
                        "des_estado": str(p.get("desEstado") or ""),
                    })
            libros[libro] = periodos
            logger.info(f"SIRE {ruc}: {libro} -> {len(periodos)} periodo(s)")

        return {"ok": True, "error": None, "libros": libros}

    except Exception as e:
        logger.error(f"Error consultando el SIRE de {ruc}: {e}")
        return {"ok": False, "error": str(e), "libros": {}}
    finally:
        navegador.close_browser()


# Menu SOL: Revision de mis deudas > Valores pendientes de pago > Valores > Consulta valores pendientes de pago.
_MENU_VALORES_PENDIENTES = ("nivel1_15", "nivel2_15_1", "nivel3_15_1_1", "nivel4_15_1_1_1_1")
# Desde que periodo se revisan los valores (pedido: "desde el ejercicio 2020").
PERIODO_INICIO_VALORES = "202001"
# La pantalla de SUNAT no acepta rangos de mas de 6 meses (validacion "menorSeisMeses").
_MESES_POR_CONSULTA_VALORES = 6
_ZONA_LIMA = timezone(timedelta(hours=-5))
_MARCA_LISTADO_VALORES = b"var ListadoValores ="


def _ultimo_periodo_consultable_valores(hoy: datetime | None = None) -> str:
    """El mes anterior al actual (hora Peru): SUNAT rechaza el periodo en curso ("periodoMenorActual")."""
    hoy = hoy or datetime.now(_ZONA_LIMA)
    anio, mes = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    return f"{anio}{mes:02d}"


def tramos_periodos(desde: str, hasta: str, meses: int = _MESES_POR_CONSULTA_VALORES) -> list[tuple[str, str]]:
    """Parte el rango AAAAMM..AAAAMM en tramos de `meses` meses como maximo, en orden."""
    inicio = int(desde[:4]) * 12 + int(desde[4:]) - 1
    fin = int(hasta[:4]) * 12 + int(hasta[4:]) - 1
    tramos = []
    while inicio <= fin:
        cierre = min(inicio + meses - 1, fin)
        tramos.append((f"{inicio // 12}{inicio % 12 + 1:02d}", f"{cierre // 12}{cierre % 12 + 1:02d}"))
        inicio = cierre + 1
    return tramos


def extraer_listado_valores(html: bytes) -> list[dict] | None:
    """
    La pantalla de resultados no trae una tabla HTML: la arma en el navegador
    desde `var ListadoValores = [...]` (JSON). None si la respuesta no es esa
    pantalla (sesion vencida, pagina de error de SUNAT).

    Ojo con la codificacion: la plantilla es UTF-8 pero los datos vienen en
    Latin-1 ("Resoluci\\xf3n de Multa", confirmado con Bascat 20/10/2026), asi
    que se decodifica solo el JSON, probando UTF-8 primero por si SUNAT lo
    corrige algun dia.
    """
    inicio = html.find(_MARCA_LISTADO_VALORES)
    if inicio < 0:
        return None
    resto = html[inicio + len(_MARCA_LISTADO_VALORES):]
    try:
        texto = resto.decode("utf-8")
    except UnicodeDecodeError:
        texto = resto.decode("cp1252", errors="replace")
    listado, _ = json.JSONDecoder().raw_decode(texto.lstrip())
    return listado


def _texto(valor) -> str:
    return str(valor if valor is not None else "").strip()


def _fecha_iso(ddmmaaaa) -> str | None:
    try:
        fecha = datetime.strptime(_texto(ddmmaaaa), "%d/%m/%Y")
    except ValueError:
        return None
    return fecha.date().isoformat() if fecha.year > 1900 else None


def _monto(valor) -> float:
    try:
        return round(float(_texto(valor) or 0), 2)
    except ValueError:
        return 0.0


def normalizar_valor(crudo: dict) -> dict:
    """Pasa un elemento de ListadoValores (nombres internos de SUNAT) a los campos que guarda el sistema."""
    periodo = _texto(crudo.get("perDoc"))
    etapa = _texto(crudo.get("desEtaBas")) or _texto(crudo.get("desEta"))
    etapa_cod = _texto(crudo.get("codEta"))
    return {
        "num_valor": _texto(crudo.get("numVal")),
        "tipo": _texto(crudo.get("desCor")),  # OP, RM, RD...
        "tipo_descripcion": _texto(crudo.get("desLar")),  # Orden de Pago, Resolucion de Multa...
        "periodo": f"{periodo[:4]}-{periodo[4:]}" if len(periodo) == 6 and periodo.isdigit() else periodo,
        "cod_tributo": _texto(crudo.get("codTri")),
        "tributo": _texto(crudo.get("descLarTrib")),
        "fecha_emision": _fecha_iso(crudo.get("strFecEmi")),
        "fecha_notificacion": _fecha_iso(crudo.get("strFecNot")),
        "estado": _texto(crudo.get("desEst")),
        "etapa_cod": etapa_cod,
        "etapa": etapa,
        "etapa_alterna": _texto(crudo.get("desEtaAlt")),
        "en_cobranza_coactiva": etapa_cod == "03" or "coactiva" in etapa.lower(),
        "num_expediente_coactivo": _texto(crudo.get("numExpCoa")) or None,
        "monto_tributo": _monto(crudo.get("mtoTri")),  # importe original del valor
        # Lo que queda del tributo (sin intereses): baja con pagos parciales
        # (Bascat 0300014730682: original 1,831 -> pendiente 434).
        "tributo_pendiente": _monto(crudo.get("montoTributoSolesAct")),
        "interes": _monto(crudo.get("montoInteresSolesAct")),
        "saldo_total": _monto(crudo.get("saldoTotal")),
        "saldo_exigible": _monto(crudo.get("saldoExigible")),
    }


# Menu SOL: Revision de mis deudas > Consultas de Cobranza > Consulta de Embargos Notificados.
_MENU_EMBARGOS = ("nivel1_15", "nivel2_15_7", "nivel3_15_7_1", "nivel4_15_7_1_1_1")
# El boton Buscar de esa pantalla exige un filtro, pero es solo validacion del
# navegador: sin filtros el servidor devuelve TODO el historial de embargos
# de la empresa en una sola respuesta (confirmado con Bascat 20/10/2026).
_URL_EMBARGOS = (
    "/ol-ti-itembtercero/mantMonto.htm?accion=buscarEmbNotificadosDeudor"
    "&rcEmbargo=&rucTercero=&estado=0&fecInicial=&fecFinal="
)
# Menu SOL: Revision de mis deudas > Valores > Consulta de REC.
_MENU_REC = ("nivel1_15", "nivel2_15_1", "nivel3_15_1_1", "nivel4_15_1_1_1_3")
_URL_RECS = "/ol-ti-itreccentral/expcoa/listarRECs/"
# La consulta de REC acepta rangos de hasta 180 dias de fecha de emision.
_DIAS_POR_CONSULTA_REC = 180
_REC_DESDE = datetime(2023, 1, 1)

_JS_FETCH_JSON = """
var done = arguments[arguments.length - 1];
fetch(arguments[0], {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: arguments[1]})
  .then(function (r) { return r.text().then(function (t) { done([r.status, t]); }); })
  .catch(function (e) { done([0, String(e)]); });
"""


def _rc_o_none(valor) -> str | None:
    texto = _texto(valor)
    return None if texto in ("", "0") else texto


def normalizar_embargo(crudo: dict) -> dict:
    return {
        "rc_embargo": _texto(crudo.get("rcEmbargo")),
        "ruc_tercero": _texto(crudo.get("numRucTer")),
        "nombre_tercero": _texto(crudo.get("nomTercero")),
        "fecha_registro": _fecha_iso(crudo.get("fecRegistro")),
        "fecha_notificacion": _fecha_iso(crudo.get("fecNotif")),
        "estado": _texto(crudo.get("estado")),
        "monto_embargado": _monto(crudo.get("monEmbargado")),
        "monto_entregado": _monto(crudo.get("monEntregado")),
        "monto_pendiente": _monto(crudo.get("monPendiente")),
        "rc_levantamiento": _rc_o_none(crudo.get("rcLevantamiento")),
        "fecha_levantamiento": _fecha_iso(crudo.get("fecLev")),
        "imposibilidad": _texto(crudo.get("desImposibilidad")),
    }


def normalizar_rec(crudo: dict) -> dict:
    return {
        "num_rec": _texto(crudo.get("num_exp_coa")),
        "dependencia": _texto(crudo.get("desc_dep")),
        "estado": _texto(crudo.get("est_rec")),
        "fecha_emision": _fecha_iso(crudo.get("fec_emi")),
        "fecha_notificacion": _fecha_iso(crudo.get("fec_not")),
    }


def _leer_embargos_notificados(navegador) -> list[dict] | None:
    try:
        error_menu = _abrir_opcion_menu_sol(navegador, _MENU_EMBARGOS, "15.7.1.1.1", "la Consulta de Embargos Notificados")
        if error_menu:
            logger.warning(f"Embargos: {error_menu}")
            return None
        time.sleep(3)
        status, cuerpo = navegador.driver.execute_async_script(_JS_FETCH_JSON, _URL_EMBARGOS, "")
        datos = json.loads(cuerpo) if status == 200 else None
        if not isinstance(datos, dict) or "listaEmbNotificados" not in datos:
            logger.warning(f"Embargos: respuesta inesperada (HTTP {status}): {str(cuerpo)[:200]}")
            return None
        embargos = [normalizar_embargo(e) for e in datos.get("listaEmbNotificados") or []]
        return [e for e in embargos if e["rc_embargo"]]
    except Exception as e:
        logger.warning(f"No se pudieron leer los embargos notificados: {e}")
        return None


def _leer_recs(navegador, ruc: str) -> list[dict] | None:
    try:
        error_menu = _abrir_opcion_menu_sol(navegador, _MENU_REC, "15.1.1.1.3", "la Consulta de REC")
        if error_menu:
            logger.warning(f"REC: {error_menu}")
            return None
        time.sleep(3)
        recs: dict[str, dict] = {}
        inicio = _REC_DESDE
        hoy = datetime.now()
        while inicio <= hoy:
            fin = min(inicio + timedelta(days=_DIAS_POR_CONSULTA_REC - 1), hoy)
            cuerpo = json.dumps({
                "cod_dep": "9999", "num_ruc": ruc, "num_rec": "", "cod_est_rec": "9999", "cod_tip_rec": "9999",
                "fecDesde": inicio.strftime("%d/%m/%Y"), "fecHasta": fin.strftime("%d/%m/%Y"), "flagsol": "1",
            })
            status, texto = navegador.driver.execute_async_script(_JS_FETCH_JSON, _URL_RECS, cuerpo)
            datos = json.loads(texto) if status == 200 else None
            if not isinstance(datos, dict) or datos.get("estadoRespuesta") != 1:
                logger.warning(f"REC: respuesta inesperada (HTTP {status}): {str(texto)[:200]}")
                return None
            for crudo in datos.get("datos") or []:
                rec = normalizar_rec(crudo)
                if rec["num_rec"]:
                    recs[rec["num_rec"]] = rec
            inicio = fin + timedelta(days=1)
            time.sleep(0.3)
        return list(recs.values())
    except Exception as e:
        logger.warning(f"No se pudieron leer las REC: {e}")
        return None


def consultar_valores_pendientes(
    ruc: str,
    usuario_sol: str,
    clave_sol: str,
    razon_social: str = "",
    headless: bool = True,
    on_progreso=None,
    desde: str = PERIODO_INICIO_VALORES,
) -> dict:
    """
    SOLO LECTURA: abre "Consulta valores pendientes de pago" y pide, desde la
    propia pantalla y con su misma sesion, el mismo POST que hace su boton
    Consultar -- una vez por cada tramo de 6 meses entre `desde` y el mes
    pasado. No usa "Generar Reporte" (SUNAT lo limita a 3 por dia).

    Solo devuelve ok=True si TODOS los tramos se leyeron: el llamador marca
    como "ya no aparece" lo que no venga en la lista, asi que una lectura a
    medias haria parecer pagadas deudas que siguen vigentes.

    Returns:
        {"ok": bool, "error": str | None, "desde": "AAAAMM", "hasta": "AAAAMM",
         "valores": [normalizar_valor(...), ...]}
    """
    def _reportar(etapa: str):
        if on_progreso is None:
            return
        try:
            on_progreso(etapa)
        except Exception as e:
            logger.warning(f"El callback de progreso fallo (no es grave, se sigue igual): {e}")

    hasta = _ultimo_periodo_consultable_valores()
    resultado_vacio = {"ok": False, "error": None, "desde": desde, "hasta": hasta, "valores": []}
    empresa = {"ruc": ruc, "usuario": usuario_sol, "clave": clave_sol, "razon_social": razon_social}
    navegador = SunatWebNavigator(empresa=empresa, headless=headless)
    try:
        if not navegador.initialize_browser():
            return {**resultado_vacio, "error": "No se pudo iniciar el navegador"}

        _reportar("iniciando_sesion")
        navegador.driver.get(config.URL_SUNAT)
        time.sleep(3)

        _reportar("autenticando")
        if not navegador._hacer_clicks_sunat(empresa):
            return {**resultado_vacio, "error": error_inicio_sesion(navegador), "credenciales_rechazadas": navegador.credenciales_rechazadas}

        _reportar("abriendo_deudas")
        error_menu = _abrir_opcion_menu_sol(
            navegador, _MENU_VALORES_PENDIENTES, "15.1.1.1.1", "la consulta de Valores pendientes de pago"
        )
        if error_menu:
            return {**resultado_vacio, "error": error_menu}
        driver = navegador.driver
        try:
            WebDriverWait(driver, 40).until(lambda d: d.find_elements(By.ID, "txtStartDate"))
        except Exception:
            navegador._guardar_captura_error("valores_sin_formulario")
            return {**resultado_vacio, "error": "La consulta de Valores pendientes de pago no termino de cargar"}

        _reportar("leyendo_deudas")
        driver.set_script_timeout(90)
        por_numero: dict[str, dict] = {}
        for ini, fin in tramos_periodos(desde, hasta):
            status, cuerpo_b64 = driver.execute_async_script(
                """
                var done = arguments[arguments.length - 1];
                var cuerpo = new URLSearchParams({txtStartDate: arguments[0], txtEndDate: arguments[1], txtNumValor: ''});
                fetch('consulta', {method: 'POST', body: cuerpo, credentials: 'include'})
                  .then(function (r) { return r.arrayBuffer().then(function (buf) {
                      var bytes = new Uint8Array(buf), bin = '';
                      for (var i = 0; i < bytes.length; i += 8192) {
                          bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
                      }
                      done([r.status, btoa(bin)]);
                  }); })
                  .catch(function (e) { done([0, '']); });
                """,
                ini, fin,
            )
            listado = extraer_listado_valores(base64.b64decode(cuerpo_b64 or "")) if status == 200 else None
            if listado is None:
                logger.warning(f"Valores {ruc}: el tramo {ini}-{fin} no devolvio el listado (HTTP {status})")
                navegador._guardar_captura_error("valores_tramo_sin_listado")
                return {**resultado_vacio, "error": f"SUNAT no devolvio la lista de valores del tramo {ini}-{fin} (HTTP {status})"}
            for crudo in listado:
                valor = normalizar_valor(crudo)
                if valor["num_valor"]:
                    por_numero[valor["num_valor"]] = valor
            time.sleep(0.5)

        logger.info(f"Valores pendientes {ruc}: {len(por_numero)} valor(es) entre {desde} y {hasta}")

        # Embargos y REC: en la MISMA sesion (sin otro ingreso a SUNAT). Un
        # fallo aca no invalida los valores ya leidos: se devuelve None y el
        # llamador deja lo guardado de esos dos como estaba.
        _reportar("leyendo_embargos")
        embargos = _leer_embargos_notificados(navegador)
        recs = _leer_recs(navegador, ruc)
        return {
            "ok": True, "error": None, "desde": desde, "hasta": hasta, "valores": list(por_numero.values()),
            "embargos": embargos, "recs": recs,
        }

    except Exception as e:
        logger.error(f"Error consultando los valores pendientes de {ruc}: {e}")
        return {**resultado_vacio, "error": str(e)}
    finally:
        navegador.close_browser()


# Menu SOL: Mis declaraciones informativas > Consulto mis declaraciones y pagos >
# Declaraciones y pagos > Consulta general.
_MENU_CONSULTA_DECLARACIONES = ("nivel1_12", "nivel2_12_8", "nivel3_12_8_1", "nivel4_12_8_1_1_2")
_URL_CONSULTA_DECLARACIONES = "/cl-ti-itconsdecdetinf/consultaS01Alias"
# Encabezado de la pantalla de resultados -- sale aunque el rango no tenga
# ninguna declaracion; si falta, la respuesta no es la consulta (sesion
# vencida, pagina de error).
_MARCA_RESULTADO_DECLARACIONES = "DETALLE DE DECLARACIONES Y PAGOS"


def _texto_celda(fragmento: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", fragmento))).strip()


def _importe_es_pe(texto: str) -> float:
    """'17.522,00' -> 17522.0 (formato de miles con punto y decimales con coma de esta pantalla)."""
    try:
        return round(float(texto.replace(".", "").replace(",", ".")), 2)
    except ValueError:
        return 0.0


def extraer_declaraciones(html_texto: str) -> list[dict] | None:
    """
    Filas de la tabla "Periodo | N° Form | N° Orden | Descripcion | Fecha de Pres. |
    Banco | Codigo-Tributo | (detalle) | Importe pagado" de la Consulta general.
    None si la respuesta no es esa pantalla.
    """
    if _MARCA_RESULTADO_DECLARACIONES not in html_texto:
        return None
    filas = []
    for fila in re.findall(r"<tr[^>]*>(.*?)</tr>", html_texto, re.S | re.I):
        celdas = [_texto_celda(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S | re.I)]
        if len(celdas) != 10 or not re.fullmatch(r"\d{6}", celdas[1]) or not re.fullmatch(r"\d{3,4}", celdas[2]):
            continue
        periodo, formulario, num_orden, descripcion, fecha, banco, tributo, _detalle, importe = celdas[1:10]
        filas.append({
            "periodo": f"{periodo[:4]}-{periodo[4:]}",
            "formulario": formulario.zfill(4),
            "num_orden": num_orden,
            "descripcion": descripcion,
            "fecha_presentacion": _fecha_iso(fecha),
            "banco": "" if banco == "-" else banco,
            "cod_tributo": "" if tributo == "-" else tributo,
            "importe_pagado": _importe_es_pe(importe),
        })
    return filas


def consultar_declaraciones(
    ruc: str,
    usuario_sol: str,
    clave_sol: str,
    razon_social: str = "",
    headless: bool = True,
    on_progreso=None,
    desde: str = PERIODO_INICIO_VALORES,
) -> dict:
    """
    SOLO LECTURA: "Consulta general" de declaraciones y pagos por periodo
    tributario (formularios 0621, 0601 PLAME, boletas 1662, etc.), con la misma
    sesion y el mismo POST de su boton Buscar, en tramos de 6 meses (limite de
    la pantalla) desde `desde` hasta el mes pasado.

    Returns:
        {"ok": bool, "error": str | None, "desde": "AAAAMM", "hasta": "AAAAMM",
         "declaraciones": [{"periodo", "formulario", "num_orden", "descripcion",
                            "fecha_presentacion", "banco", "cod_tributo", "importe_pagado"}]}
    """
    def _reportar(etapa: str):
        if on_progreso is None:
            return
        try:
            on_progreso(etapa)
        except Exception as e:
            logger.warning(f"El callback de progreso fallo (no es grave, se sigue igual): {e}")

    hasta = _ultimo_periodo_consultable_valores()
    resultado_vacio = {"ok": False, "error": None, "desde": desde, "hasta": hasta, "declaraciones": []}
    empresa = {"ruc": ruc, "usuario": usuario_sol, "clave": clave_sol, "razon_social": razon_social}
    navegador = SunatWebNavigator(empresa=empresa, headless=headless)
    try:
        if not navegador.initialize_browser():
            return {**resultado_vacio, "error": "No se pudo iniciar el navegador"}

        _reportar("iniciando_sesion")
        navegador.driver.get(config.URL_SUNAT)
        time.sleep(3)

        _reportar("autenticando")
        if not navegador._hacer_clicks_sunat(empresa):
            return {**resultado_vacio, "error": error_inicio_sesion(navegador), "credenciales_rechazadas": navegador.credenciales_rechazadas}

        _reportar("abriendo_declaraciones")
        error_menu = _abrir_opcion_menu_sol(
            navegador, _MENU_CONSULTA_DECLARACIONES, "12.8.1.1.2", "la Consulta general de declaraciones y pagos"
        )
        if error_menu:
            return {**resultado_vacio, "error": error_menu}
        driver = navegador.driver
        try:
            WebDriverWait(driver, 40).until(lambda d: d.find_elements(By.NAME, "consultageneral"))
        except Exception:
            navegador._guardar_captura_error("declaraciones_sin_formulario")
            return {**resultado_vacio, "error": "La Consulta general de declaraciones no termino de cargar"}

        _reportar("leyendo_declaraciones")
        driver.set_script_timeout(90)
        vistas: dict[tuple, dict] = {}
        for ini, fin in tramos_periodos(desde, hasta):
            status, cuerpo_b64 = driver.execute_async_script(
                """
                var done = arguments[arguments.length - 1];
                var cuerpo = new URLSearchParams({
                    accion: 'consultageneral', busquedapor: 'periodo', declaracion: '1', formu2: 'TODOS',
                    importepagado: '1', adesde: arguments[1], mdesde: arguments[2], ahasta: arguments[3],
                    mhasta: arguments[4], fec_preini: '', fec_prefin: ''});
                fetch(arguments[0], {method: 'POST', body: cuerpo, credentials: 'include'})
                  .then(function (r) { return r.arrayBuffer().then(function (buf) {
                      var bytes = new Uint8Array(buf), bin = '';
                      for (var i = 0; i < bytes.length; i += 8192) {
                          bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
                      }
                      done([r.status, btoa(bin)]);
                  }); })
                  .catch(function (e) { done([0, '']); });
                """,
                _URL_CONSULTA_DECLARACIONES, ini[:4], ini[4:], fin[:4], fin[4:],
            )
            # Esta pantalla viene en Latin-1 (confirmado con Bascat 20/10/2026).
            filas = extraer_declaraciones(base64.b64decode(cuerpo_b64 or "").decode("cp1252", errors="replace")) if status == 200 else None
            if filas is None:
                logger.warning(f"Declaraciones {ruc}: el tramo {ini}-{fin} no devolvio la consulta (HTTP {status})")
                navegador._guardar_captura_error("declaraciones_tramo_sin_resultado")
                return {**resultado_vacio, "error": f"SUNAT no devolvio las declaraciones del tramo {ini}-{fin} (HTTP {status})"}
            for fila in filas:
                vistas[(fila["formulario"], fila["num_orden"], fila["cod_tributo"])] = fila
            time.sleep(0.5)

        logger.info(f"Declaraciones {ruc}: {len(vistas)} formulario(s) entre {desde} y {hasta}")
        return {"ok": True, "error": None, "desde": desde, "hasta": hasta, "declaraciones": list(vistas.values())}

    except Exception as e:
        logger.error(f"Error consultando las declaraciones de {ruc}: {e}")
        return {**resultado_vacio, "error": str(e)}
    finally:
        navegador.close_browser()


# "Mis Declaraciones y Pagos" (la plataforma nueva, no el Menu SOL clasico) >
# Consultas > Consultas de Presentacion y Pago > Consulta de Pago de
# Detracciones. La opcion abre con un enlace directo (exe=) y su pantalla
# consulta un servicio JSON con el token de la sesion (sessionStorage
# "token" -> cabecera IdCache): el mismo pedido que hace su boton Consultar.
# Probado con Bascat el 21/10/2026.
_URL_SOL_INICIO = "https://www.sunat.gob.pe/sol.html"
_URL_OPCION_DETRACCIONES = (
    "https://e-menu.sunat.gob.pe/cl-ti-itmenu2/MenuInternetPlataforma.htm?pestana=*&agrupacion=*&exe=55.2.1.1.4"
)
_URL_API_DETRACCIONES = "https://e-plataformaunica.sunat.gob.pe/v1/recaudacion/tributaria/declapago/detracciones/t/consultar"
TIPOS_CUENTA_DETRACCION = {"1": "Convencional", "2": "Especial IVAP", "3": "Ley N° 30737"}
TIPOS_PAGO_DETRACCION = {
    "pagosIndividuales": "Pagos individuales",
    "pagosMasivos": "Pagos masivos",
    "pagosTransPasajeros": "Pagos transporte de pasajeros",
}
# SUNAT rechaza (cod 412) un rango de fechas de pago mayor a 30 dias.
DIAS_POR_CONSULTA_DETRACCIONES = 30


def tramos_fechas(desde: date, hasta: date, dias: int = DIAS_POR_CONSULTA_DETRACCIONES) -> list[tuple[date, date]]:
    """[desde, hasta] partido en tramos de `dias` dias contando ambos extremos."""
    tramos = []
    ini = desde
    while ini <= hasta:
        fin = min(ini + timedelta(days=dias - 1), hasta)
        tramos.append((ini, fin))
        ini = fin + timedelta(days=1)
    return tramos


def _monto(valor) -> float:
    try:
        return round(float(str(valor).replace(",", "")), 2)
    except (TypeError, ValueError):
        return 0.0


def normalizar_detraccion(crudo: dict, tipo_pago: str) -> dict:
    """Un deposito tal como lo devuelve el servicio de SUNAT, con nombres propios y sin espacios de relleno."""
    def t(clave):
        valor = crudo.get(clave)
        return "" if valor is None else str(valor).strip()

    periodo = t("per_tributario")
    constancia = t("num_constancia") or f"{t('num_pres')}-{t('num_serie')}-{t('num_comprobante')}"
    monto = crudo.get("mto_deposito")
    return {
        "num_constancia": constancia,
        "tipo_cuenta": t("cod_tipcta"),
        "num_cuenta": t("num_cuenta"),
        "fecha_pago": t("fec_pago_desc")[:10] or None,
        "periodo": f"{periodo[:4]}-{periodo[4:6]}" if len(periodo) >= 6 else "",
        "tipo_comprobante": t("cod_tipcomprobante"),
        "serie": t("num_serie"),
        "numero": t("num_comprobante"),
        "ruc_proveedor": t("num_ruc_proveedor"),
        "proveedor": t("des_prov"),
        "tipo_doc_adquiriente": t("tip_doc_adq"),
        "doc_adquiriente": t("num_doc_adq"),
        "adquiriente": t("des_adq"),
        "tipo_operacion": t("tip_operacion"),
        "tipo_bien": t("tip_bien"),
        "monto": _monto(monto if monto is not None else crudo.get("mto_deposito_desc")),
        "num_pago": t("num_npd"),
        "num_presentacion": t("num_pres"),
        "origen": t("origen_desc"),
        "tipo_pago": tipo_pago,
    }


# Una consulta de detracciones a veces queda colgada en SUNAT: se corta a los
# 45 s y se reintenta (con pausa) antes de dar el tramo por fallido.
_SEGUNDOS_MAX_CONSULTA_DETRACCIONES = 45
_INTENTOS_CONSULTA_DETRACCIONES = 3


# Una respuesta lenta o que necesito reintento puede venir incompleta (medido
# 22/10/2026: diciembre 2023 de Bascat devolvio 8 depositos con SUNAT cargado
# y 28 al repetirlo): esas consultas se leen otra vez y se juntan.
_SEGUNDOS_RESPUESTA_DUDOSA = 10


def _consultar_api_detracciones(driver, url: str) -> tuple[int, str, bool]:
    """(status, cuerpo, dudosa): dudosa = tardo mas de 10 s o hubo que reintentar."""
    status, cuerpo = 0, ""
    for intento in range(1, _INTENTOS_CONSULTA_DETRACCIONES + 1):
        inicio = time.monotonic()
        status, cuerpo = driver.execute_async_script(
            """
            var done = arguments[arguments.length - 1];
            var corte = new AbortController();
            var reloj = setTimeout(function () { corte.abort(); }, arguments[1] * 1000);
            fetch(arguments[0], {credentials: 'include', signal: corte.signal, headers: {
                'IdCache': sessionStorage.getItem('token'), 'IdFormulario': '*MENU*'}})
              .then(function (r) { return r.text().then(function (t) { clearTimeout(reloj); done([r.status, t]); }); })
              .catch(function (e) { clearTimeout(reloj); done([0, String(e)]); });
            """,
            url, _SEGUNDOS_MAX_CONSULTA_DETRACCIONES,
        )
        if status == 200:
            dudosa = intento > 1 or time.monotonic() - inicio > _SEGUNDOS_RESPUESTA_DUDOSA
            return status, cuerpo, dudosa
        logger.warning(f"Consulta de detracciones sin respuesta (intento {intento}, HTTP {status}): {str(cuerpo)[:120]}")
        time.sleep(10 * intento)
    return status, cuerpo, True


def _entrar_mis_declaraciones_y_pagos(navegador: SunatWebNavigator, empresa: dict) -> str | None:
    """Login a la plataforma "Mis Declaraciones y Pagos" (mismo boton que su tarjeta en sol.html). None si entro."""
    driver = navegador.driver
    driver.get(_URL_SOL_INICIO)
    WebDriverWait(driver, 30).until(lambda d: d.execute_script("return typeof declaraSimplificadaNueva === 'function'"))
    original = driver.current_window_handle
    driver.execute_script("declaraSimplificadaNueva()")
    WebDriverWait(driver, 20).until(lambda d: len(d.window_handles) > 1)
    driver.switch_to.window([w for w in driver.window_handles if w != original][-1])
    WebDriverWait(driver, 30).until(lambda d: "loginMenuSol" in d.current_url)
    if not navegador._ingresar_credenciales(empresa):
        return error_inicio_sesion(navegador)
    try:
        navegador._click_condicional()
    except Exception as e:
        logger.info(f"Detracciones: sin modales tras el login ({e})")
    try:
        WebDriverWait(driver, 40).until(lambda d: "MenuInternetPlataforma" in d.current_url)
    except Exception:
        navegador._guardar_captura_error("detracciones_sin_plataforma")
        return "No se pudo entrar a Mis Declaraciones y Pagos"
    return None


def consultar_detracciones(
    ruc: str,
    usuario_sol: str,
    clave_sol: str,
    razon_social: str = "",
    headless: bool = True,
    on_progreso=None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    periodo: str | None = None,
    tipos_cuenta: tuple = ("1",),
    tipos_pago: tuple = ("pagosIndividuales",),
    on_tramo=None,
) -> dict:
    """
    SOLO LECTURA: "Consulta de Pago de Detracciones" (SPOT) con los mismos
    filtros de la pantalla: por fecha de pago (tramos de 30 dias, limite de
    SUNAT) o por periodo tributario ("AAAAMM"), para cada tipo de cuenta y
    tipo de pago pedido. Trae los depositos que la empresa recibio en su
    cuenta (es el proveedor) y los que hizo a sus proveedores (adquiriente).

    `on_tramo(desde, hasta, depositos)`: se llama al terminar cada tramo de
    fechas (todas sus cuentas y tipos de pago), para que la carga del historial
    guarde su avance aunque un tramo posterior falle.

    Returns:
        {"ok": bool, "error": str | None, "detracciones": [normalizar_detraccion(...)],
         "consultas": int, "credenciales_rechazadas": bool}
    """
    def _reportar(etapa: str):
        if on_progreso is None:
            return
        try:
            on_progreso(etapa)
        except Exception as e:
            logger.warning(f"El callback de progreso fallo (no es grave, se sigue igual): {e}")

    resultado_vacio = {"ok": False, "error": None, "detracciones": [], "consultas": 0}
    if periodo:
        busquedas = [(None, None, periodo)]
    elif fecha_desde and fecha_hasta and fecha_desde <= fecha_hasta:
        busquedas = [(i, f, "") for i, f in tramos_fechas(fecha_desde, fecha_hasta)]
    else:
        return {**resultado_vacio, "error": "Indica un rango de fechas de pago o un periodo tributario"}

    empresa = {"ruc": ruc, "usuario": usuario_sol, "clave": clave_sol, "razon_social": razon_social}
    navegador = SunatWebNavigator(empresa=empresa, headless=headless)
    try:
        if not navegador.initialize_browser():
            return {**resultado_vacio, "error": "No se pudo iniciar el navegador"}

        _reportar("autenticando")
        error_login = _entrar_mis_declaraciones_y_pagos(navegador, empresa)
        if error_login:
            return {**resultado_vacio, "error": error_login, "credenciales_rechazadas": navegador.credenciales_rechazadas}

        _reportar("abriendo_detracciones")
        driver = navegador.driver
        driver.get(_URL_OPCION_DETRACCIONES)
        # El src del iframe es la URL del menu (action=execute...); la pantalla
        # real (e-plataformaunica) es a donde redirige, asi que se mira la
        # ubicacion de adentro de cada marco y que ya tenga el token.
        listo = False
        for _ in range(45):
            for marco in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    driver.switch_to.frame(marco)
                    listo = bool(driver.execute_script(
                        "return location.host.indexOf('plataformaunica') >= 0 && !!sessionStorage.getItem('token')"
                    ))
                except Exception:
                    listo = False
                if listo:
                    break
                driver.switch_to.default_content()
            if listo:
                break
            time.sleep(1)
        if not listo:
            navegador._guardar_captura_error("detracciones_sin_pantalla")
            return {**resultado_vacio, "error": "La Consulta de Pago de Detracciones no termino de cargar"}

        _reportar("leyendo_detracciones")
        # Por periodo SUNAT tarda ~20 s por consulta (por fecha, menos de 1 s);
        # cada consulta se corta sola a los 45 s (ver _consultar_api_detracciones).
        driver.set_script_timeout(_SEGUNDOS_MAX_CONSULTA_DETRACCIONES + 30)
        por_clave: dict[tuple, dict] = {}
        consultas = 0
        for ini_fecha, fin_fecha, per in busquedas:
            ini = ini_fecha.strftime("%d/%m/%Y") if ini_fecha else ""
            fin = fin_fecha.strftime("%d/%m/%Y") if fin_fecha else ""
            del_tramo: dict[tuple, dict] = {}
            for tipo_cuenta in tipos_cuenta:
                for tipo_pago in tipos_pago:
                    url = (
                        f"{_URL_API_DETRACCIONES}?&fechaInicio={ini}&fechaFin={fin}&tipoCuenta={tipo_cuenta}"
                        f"&tipoConsulta={tipo_pago}&periodo={per}"
                    )
                    status, cuerpo, dudosa = _consultar_api_detracciones(driver, url)
                    consultas += 1
                    try:
                        datos = json.loads(cuerpo) if status == 200 else None
                    except ValueError:
                        datos = None
                    if not isinstance(datos, dict):
                        logger.warning(f"Detracciones {ruc}: respuesta inesperada (HTTP {status}) para {ini}-{fin}{per}")
                        return {**resultado_vacio, "error": f"SUNAT no respondio la consulta de detracciones (HTTP {status})"}
                    if datos.get("cod") != 200:
                        detalle = "; ".join(e.get("msg", "") for e in datos.get("errores") or []) or datos.get("msg") or ""
                        return {**resultado_vacio, "error": "SUNAT rechazo la consulta: " + re.sub(r"<[^>]+>", " ", detalle).strip()}
                    resultados = list(datos.get("resultado") or [])
                    if dudosa:
                        status2, cuerpo2, _ = _consultar_api_detracciones(driver, url)
                        try:
                            datos2 = json.loads(cuerpo2) if status2 == 200 else None
                        except ValueError:
                            datos2 = None
                        if isinstance(datos2, dict) and datos2.get("cod") == 200:
                            resultados += datos2.get("resultado") or []
                    for crudo in resultados:
                        d = normalizar_detraccion(crudo, tipo_pago)
                        del_tramo[(d["num_constancia"], d["tipo_cuenta"] or tipo_cuenta)] = d
                    time.sleep(0.3)
            por_clave.update(del_tramo)
            if on_tramo is not None and ini_fecha:
                on_tramo(ini_fecha, fin_fecha, list(del_tramo.values()))

        logger.info(f"Detracciones {ruc}: {len(por_clave)} deposito(s) en {consultas} consulta(s)")
        return {"ok": True, "error": None, "detracciones": list(por_clave.values()), "consultas": consultas}

    except Exception as e:
        logger.error(f"Error consultando las detracciones de {ruc}: {e}")
        return {**resultado_vacio, "error": str(e)}
    finally:
        navegador.close_browser()
