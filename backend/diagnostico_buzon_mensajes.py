#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de DIAGNOSTICO (no toca produccion, no descarga nada, solo lee) --
inicia sesion real en SUNAT para una empresa ya guardada en la base de
datos y junta evidencia de la seccion "Buzon Mensajes" (distinta de
"Buzon Notificaciones", que es la unica que hoy scrapea la app) para
poder disenar su scraping:

1. Como se llega a "Buzon Mensajes" desde el Buzon Electronico normal --
   texto/id del enlace en el sidebar, si esta en el mismo iframe que la
   lista de "Buzon Notificaciones" o en otro.
2. Estructura de la lista de mensajes de esa bandeja -- si trae una
   ETIQUETA/categoria visible por mensaje (el usuario menciono ver un
   badge de color, ej. "RESOLUCIONES DE COBRANZA", en capturas de la
   bandeja de Notificaciones -- hay que confirmar si Mensajes tiene lo
   mismo).
3. Estructura de la vista de detalle de UN mensaje -- donde esta el
   CONTENIDO COMPLETO en texto (esta bandeja no tiene PDF adjunto, a
   diferencia de Notificaciones).

Como correrlo (PowerShell, desde la carpeta buzon-saas):
    docker-compose exec worker python diagnostico_buzon_mensajes.py <RUC>

Si no se pasa RUC, usa el primero que encuentre en la base de datos con
credenciales guardadas. El resultado queda en sunat_data/logs/ con el
prefijo "diagnostico_buzon_mensajes_<RUC>_...". Comparte esos archivos
(sobre todo los .html) para disenar el scraper real con evidencia en vez
de adivinar.
"""
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as core_config  # config.py de core_scraper (ya esta en PYTHONPATH)
core_config.setup_logging()

import logging
logger = logging.getLogger("diagnostico_buzon_mensajes")

from pyvirtualdisplay import Display

# Mismo motivo que worker_entry.py: SUNAT corta la conexion si detecta
# Chrome en modo headless de verdad -- se usa Xvfb + headless=False.
logger.info("Arrancando pantalla virtual (Xvfb)...")
display = Display(visible=False, size=(1600, 1000))
display.start()

from app.database import SessionLocal
from app.models import Empresa, CredencialSol
from app.security import descifrar_clave_sol

from web_navigation import SunatWebNavigator
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import config


def obtener_empresa_de_prueba(ruc: str | None):
    """Mismo patron que diagnostico_ficha_ruc.py -- ver ese archivo."""
    db = SessionLocal()
    try:
        query = (
            db.query(Empresa, CredencialSol)
            .join(CredencialSol, CredencialSol.empresa_id == Empresa.id)
            .filter(CredencialSol.dek_cifrada.isnot(None))
        )
        if ruc:
            query = query.filter(Empresa.ruc == ruc)
        else:
            query = query.order_by(Empresa.creado_en.desc())
        candidatos = query.limit(10).all()

        if not candidatos:
            sys.exit(
                f"No se encontro ninguna empresa{' con RUC ' + ruc if ruc else ''} "
                "con credenciales SOL utilizables en la base de datos."
            )

        for empresa, credencial in candidatos:
            try:
                clave = descifrar_clave_sol(credencial.clave_cifrada, credencial.dek_cifrada)
            except Exception as e:
                logger.warning(f"No se pudo descifrar la clave de {empresa.ruc} ({e}), probando la siguiente...")
                continue
            return {
                "ruc": empresa.ruc,
                "usuario": credencial.usuario_sol,
                "clave": clave,
                "razon_social": empresa.razon_social,
            }

        sys.exit("Ninguna de las empresas candidatas tiene una credencial que se pueda descifrar.")
    finally:
        db.close()


def guardar_evidencia(navegador, ruc, etiqueta):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(config.LOGS_DIR, f"diagnostico_buzon_mensajes_{ruc}_{etiqueta}_{ts}")
    try:
        navegador.driver.save_screenshot(f"{base}.png")
    except Exception as e:
        logger.warning(f"No se pudo guardar la captura de pantalla: {e}")
    try:
        with open(f"{base}.html", "w", encoding="utf-8") as f:
            f.write(navegador.driver.page_source)
    except Exception as e:
        logger.warning(f"No se pudo guardar el HTML: {e}")
    logger.info(f"Evidencia guardada: {base}.png / {base}.html")
    return base


def buscar_en_default_y_iframes(driver, buscar_fn, etiqueta_debug):
    """
    Mismo patron que _escanear_mensajes en adapter.py -- prueba primero en
    default_content, y si no encuentra nada recorre cada iframe de primer
    nivel. Devuelve (encontrado, nombre_contexto) y deja el driver
    posicionado en el contexto donde SI encontro algo.
    """
    driver.switch_to.default_content()
    resultado = buscar_fn(driver)
    if resultado:
        logger.info(f"[{etiqueta_debug}] Encontrado en default_content.")
        return resultado, "default_content"

    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    logger.info(f"[{etiqueta_debug}] Nada en default_content, probando {len(iframes)} iframe(s)...")
    for i, iframe in enumerate(iframes):
        try:
            driver.switch_to.frame(iframe)
        except Exception:
            driver.switch_to.default_content()
            continue
        resultado = buscar_fn(driver)
        if resultado:
            logger.info(f"[{etiqueta_debug}] Encontrado en iframe {i}.")
            return resultado, f"iframe_{i}"
        driver.switch_to.default_content()

    logger.warning(f"[{etiqueta_debug}] No se encontro en default_content ni en ningun iframe.")
    return None, None


def main():
    ruc_pedido = sys.argv[1].strip() if len(sys.argv) > 1 else None
    empresa = obtener_empresa_de_prueba(ruc_pedido)
    logger.info(f"Usando empresa {empresa['ruc']} - {empresa['razon_social']} (usuario/clave ocultos)")

    navegador = SunatWebNavigator(empresa=empresa, headless=False)
    archivos_generados = []
    try:
        if not navegador.initialize_browser():
            sys.exit("No se pudo iniciar el navegador")

        navegador.driver.get(config.URL_SUNAT)
        time.sleep(3)

        if not navegador._hacer_clicks_sunat(empresa):
            sys.exit("No se pudo iniciar sesion en SUNAT (revisa usuario/clave de esta empresa)")

        logger.info(f"Login OK. Razon social detectada: {navegador.razon_social_detectada}")

        if not navegador._navegar_a_buzon_notificaciones():
            sys.exit("No se pudo navegar al Buzon Electronico (fallo el paso que ya usa produccion hoy)")

        base_notif = guardar_evidencia(navegador, empresa["ruc"], "01_buzon_notificaciones")
        archivos_generados.append(f"{base_notif}.html")
        logger.info("Evidencia de Buzon Notificaciones guardada -- este es el punto de partida conocido.")

        # ---- Paso 1: encontrar y hacer clic en "Buzon Mensajes" ----
        def buscar_link_mensajes(driver):
            estrategias = [
                (By.PARTIAL_LINK_TEXT, "Buzón Mensajes"),
                (By.PARTIAL_LINK_TEXT, "Buzon Mensajes"),
                (By.XPATH, "//a[contains(text(), 'Mensajes')]"),
                (By.XPATH, "//*[contains(text(), 'Buzón Mensajes')]"),
            ]
            for by, valor in estrategias:
                try:
                    el = driver.find_element(by, valor)
                    if el:
                        return el
                except Exception:
                    continue
            return None

        elemento_mensajes, contexto = buscar_en_default_y_iframes(
            navegador.driver, buscar_link_mensajes, "buscando enlace 'Buzon Mensajes'"
        )

        if elemento_mensajes is None:
            logger.error(
                "No se encontro el enlace 'Buzon Mensajes' con las estrategias probadas. "
                "Revisa el HTML '01_buzon_notificaciones' guardado arriba para ajustar el selector a mano."
            )
        else:
            logger.info(f"Enlace 'Buzon Mensajes' encontrado en {contexto}. Intentando clic...")
            try:
                elemento_mensajes.click()
            except Exception as e:
                logger.warning(f"Clic normal fallo ({e}), probando clic por JavaScript...")
                navegador.driver.execute_script("arguments[0].click();", elemento_mensajes)
            time.sleep(4)

            base_mensajes = guardar_evidencia(navegador, empresa["ruc"], "02_buzon_mensajes_lista")
            archivos_generados.append(f"{base_mensajes}.html")
            logger.info("Evidencia de la LISTA de Buzon Mensajes guardada.")

            # ---- Paso 2: abrir el primer mensaje de la lista para ver el detalle ----
            def buscar_primer_mensaje(driver):
                # Confirmado leyendo el HTML real (02_buzon_mensajes_lista):
                # cada mensaje es <li id="..."><a class="linkMensaje" ...>ASUNTO</a>
                # ...<small class="fecPublica">FECHA</small>...</li>, dentro de
                # <ul id="listaMensajes">. class="linkMensaje" es MUY especifico --
                # nada de fallback generico "//li//a" (eso fue lo que en la
                # corrida anterior encontro un link cualquiera del menu SUNAT
                # en vez de un mensaje real).
                enlaces = driver.find_elements(By.CLASS_NAME, "linkMensaje")
                indice = int(os.environ.get("INDICE_MENSAJE", "0"))
                return enlaces[indice] if len(enlaces) > indice else None

            primer_mensaje, contexto_mensaje = buscar_en_default_y_iframes(
                navegador.driver, buscar_primer_mensaje, "buscando el primer mensaje de la lista"
            )

            if primer_mensaje is None:
                logger.error(
                    "No se encontro ningun mensaje clickeable en la lista de Buzon Mensajes. "
                    "Revisa '02_buzon_mensajes_lista' para ver la estructura real."
                )
            else:
                logger.info(
                    f"Primer mensaje encontrado en {contexto_mensaje}, asunto='{primer_mensaje.text.strip()}'. "
                    "Intentando clic..."
                )
                try:
                    primer_mensaje.click()
                except Exception as e:
                    logger.warning(f"Clic normal fallo ({e}), probando clic por JavaScript...")
                    navegador.driver.execute_script("arguments[0].click();", primer_mensaje)
                time.sleep(4)

                base_detalle = guardar_evidencia(navegador, empresa["ruc"], "03_buzon_mensajes_detalle")
                archivos_generados.append(f"{base_detalle}.html")
                logger.info("Evidencia del DETALLE de un mensaje guardada -- deberia tener el texto completo.")

                # Tambien volcamos el texto plano visible (mas facil de leer
                # a simple vista que buscar en el HTML crudo).
                try:
                    texto_visible = navegador.driver.find_element(By.TAG_NAME, "body").text
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    ruta_txt = os.path.join(
                        config.LOGS_DIR, f"diagnostico_buzon_mensajes_{empresa['ruc']}_03_detalle_texto_{ts}.txt"
                    )
                    with open(ruta_txt, "w", encoding="utf-8") as f:
                        f.write(texto_visible)
                    archivos_generados.append(ruta_txt)
                    logger.info(f"Texto visible del detalle volcado a: {ruta_txt}")
                except Exception as e:
                    logger.warning(f"No se pudo volcar el texto visible del detalle: {e}")

                # El contenido REAL del mensaje esta en un iframe anidado
                # (confirmado leyendo el HTML: <iframe id="contenedorMensaje">
                # ...) -- el body.text de arriba solo trae la lista + el
                # texto de respaldo "El browser no soporta IFRAMES...". Hay
                # que cambiar de contexto explicitamente para leer el texto
                # real del mensaje (saludo, cuerpo, tabla de compras/ventas
                # si aplica).
                try:
                    navegador.driver.switch_to.default_content()
                    # Puede estar dentro del iframe de "Buzon Mensajes"
                    # (iframe_1 en esta corrida) -- primero probamos ahi
                    # tal como quedo el driver, y si no, recorremos de nuevo.
                    def buscar_contenedor_mensaje(driver):
                        try:
                            return driver.find_element(By.ID, "contenedorMensaje")
                        except Exception:
                            return None

                    iframe_contenido, contexto_iframe = buscar_en_default_y_iframes(
                        navegador.driver, buscar_contenedor_mensaje, "buscando iframe 'contenedorMensaje'"
                    )
                    if iframe_contenido is None:
                        logger.warning(
                            "No se encontro el iframe 'contenedorMensaje' -- puede que este mensaje en particular "
                            "no use ese id, revisar el HTML '03_buzon_mensajes_detalle' a mano."
                        )
                    else:
                        logger.info(f"iframe 'contenedorMensaje' encontrado en {contexto_iframe}, entrando...")
                        navegador.driver.switch_to.frame(iframe_contenido)
                        time.sleep(1)
                        texto_contenido = navegador.driver.find_element(By.TAG_NAME, "body").text
                        html_contenido = navegador.driver.page_source
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        ruta_contenido_txt = os.path.join(
                            config.LOGS_DIR,
                            f"diagnostico_buzon_mensajes_{empresa['ruc']}_04_contenido_real_{ts}.txt",
                        )
                        ruta_contenido_html = os.path.join(
                            config.LOGS_DIR,
                            f"diagnostico_buzon_mensajes_{empresa['ruc']}_04_contenido_real_{ts}.html",
                        )
                        with open(ruta_contenido_txt, "w", encoding="utf-8") as f:
                            f.write(texto_contenido)
                        with open(ruta_contenido_html, "w", encoding="utf-8") as f:
                            f.write(html_contenido)
                        archivos_generados.append(ruta_contenido_txt)
                        archivos_generados.append(ruta_contenido_html)
                        logger.info(f"Contenido REAL del mensaje volcado a: {ruta_contenido_txt}")
                        navegador.driver.switch_to.default_content()
                except Exception as e:
                    logger.warning(f"No se pudo leer el contenido del iframe 'contenedorMensaje': {e}")

        print("\n" + "=" * 70)
        print("LISTO. Comparte estos archivos para continuar:")
        for ruta in archivos_generados:
            print(f"  {ruta}")
        print("=" * 70)

    finally:
        navegador.close_browser()
        display.stop()


if __name__ == "__main__":
    main()
