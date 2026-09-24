#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de DIAGNOSTICO (no toca produccion) -- inicia sesion real en SUNAT
para una empresa que ya esta guardada en la base de datos y junta evidencia
para dos preguntas pendientes:

1. El PDF de Ficha RUC que genera hoy la produccion (adapter.py) resulto
   ser la pantalla intermedia "Datos de Ficha RUC - Modificacion..." (con
   botones "Descargar Ficha RUC" / "Ficha RUC" / "Aceptar" / "Cancelar"),
   NO la ficha completa -- hay que hacer clic en el boton interno "Ficha
   RUC" (dentro de esa pantalla) para llegar al contenido real. Este script
   busca ese boton por su texto, le hace clic, y genera un SEGUNDO PDF
   despues del clic para comparar contra el actual.

2. Si "Estado del Contribuyente" (Activo / Baja de Oficio / etc.) se puede
   leer GRATIS en el banner normal del Menu SOL (como ya hicimos con la
   condicion de domicilio, que vive en .spanEstadoDomicilio) o si de
   verdad solo aparece dentro de la Ficha RUC. Si esta en el banner,
   se puede capturar en cada consulta normal (incluido el chequeo
   automatico de las 11am/7:30pm) sin el costo extra de abrir la Ficha
   RUC; si no, hay que decidir otro mecanismo.

Como correrlo (PowerShell, desde la carpeta buzon-saas):
    docker-compose exec worker python diagnostico_ficha_ruc.py <RUC>

Si no se pasa RUC, usa el primero que encuentre en la base de datos con
credenciales guardadas. El resultado queda en sunat_data/logs/ con el
prefijo "diagnostico_ficha_ruc_<RUC>_...". Comparte esos archivos (sobre
todo los .html y .pdf marcados "despues_del_clic") para confirmar ambas
cosas con evidencia real en vez de adivinar.
"""
import os
import sys
import time
import base64
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as core_config  # config.py de core_scraper (ya esta en PYTHONPATH)
core_config.setup_logging()

import logging
logger = logging.getLogger("diagnostico_ficha_ruc")

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

PALABRAS_CLAVE = [
    "ACTIVO", "BAJA DE OFICIO", "BAJA PROVISIONAL", "SUSPENSION",
    "HABIDO", "NO HALLADO", "ESTADO DEL CONTRIBUYENTE",
    "CONDICION DEL CONTRIBUYENTE",
]

# Texto exacto del boton interno que hay que pulsar dentro de la pantalla
# "Datos de Ficha RUC - Modificacion..." para llegar a la ficha completa
# (visible en la captura que compartio el usuario, junto a "Aceptar" y
# "Cancelar"). Se prueban las 3 formas mas comunes en que SUNAT arma sus
# botones (button / input[value] / a estilizado como boton).
XPATH_BOTON_FICHA_RUC_INTERNO = (
    "//button[normalize-space()='Ficha RUC'] "
    "| //input[@value='Ficha RUC'] "
    "| //a[normalize-space()='Ficha RUC'] "
    "| //*[@class and contains(concat(' ', normalize-space(@class), ' '), ' btn ')][normalize-space()='Ficha RUC']"
)


def obtener_empresa_de_prueba(ruc: str | None):
    """
    Busca una empresa con credenciales SOL utilizables. Si no se pide un
    RUC puntual, prueba las mas recientes primero y salta cualquier fila
    que no se pueda descifrar (p.ej. filas viejas de antes del cifrado
    envelope actual, que se quedaron con dek_cifrada vacio) en vez de
    reventar con la primera que encuentre.
    """
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
    base = os.path.join(config.LOGS_DIR, f"diagnostico_ficha_ruc_{ruc}_{etiqueta}_{ts}")
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


def buscar_palabras_clave(driver, etiqueta):
    try:
        texto = driver.find_element(By.TAG_NAME, "body").text.upper()
    except Exception as e:
        logger.warning(f"[{etiqueta}] No se pudo leer el texto de la pagina: {e}")
        return []
    encontradas = [p for p in PALABRAS_CLAVE if p in texto]
    if encontradas:
        logger.info(f"[{etiqueta}] Palabras clave encontradas: {encontradas}")
    else:
        logger.info(f"[{etiqueta}] Ninguna palabra clave encontrada.")
    return encontradas


def generar_pdf(driver, ruc, etiqueta):
    try:
        resultado_pdf = driver.execute_cdp_cmd("Page.printToPDF", {
            "printBackground": True,
            "preferCSSPageSize": True,
        })
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta_pdf = os.path.join(config.LOGS_DIR, f"diagnostico_ficha_ruc_{ruc}_{etiqueta}_{ts}.pdf")
        with open(ruta_pdf, "wb") as f:
            f.write(base64.b64decode(resultado_pdf["data"]))
        logger.info(f"[{etiqueta}] PDF generado: {ruta_pdf}")
        print(f"\nPDF GENERADO ({etiqueta}): {ruta_pdf}")
        return ruta_pdf
    except Exception as e:
        logger.error(f"[{etiqueta}] No se pudo generar el PDF: {e}")
        return None


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
        logger.info(f"Condicion de domicilio detectada: {navegador.condicion_domicilio_detectada}")

        # ---- Pregunta 2: el "Estado del Contribuyente" alguna vez aparece
        # en el Menu SOL normal (banner/dropdown), SIN entrar a Ficha RUC? ----
        base_menu = guardar_evidencia(navegador, empresa["ruc"], "01_menu_sol")
        archivos_generados.append(f"{base_menu}.html")
        logger.info("Buscando 'Estado del Contribuyente' en el Menu SOL normal (banner, SIN abrir Ficha RUC)...")
        buscar_palabras_clave(navegador.driver, "01_menu_sol (banner normal, antes de abrir el desplegable)")

        logger.info("Abriendo el desplegable del nombre de la empresa...")
        boton_nombre = WebDriverWait(navegador.driver, 10).until(
            EC.element_to_be_clickable((By.ID, "aOpcionUsuario2"))
        )
        try:
            boton_nombre.click()
        except Exception:
            navegador.driver.execute_script("arguments[0].click();", boton_nombre)
        time.sleep(2)

        base_desplegable = guardar_evidencia(navegador, empresa["ruc"], "02_desplegable_abierto")
        archivos_generados.append(f"{base_desplegable}.html")
        buscar_palabras_clave(navegador.driver, "02_desplegable_abierto (con el menu del nombre ya abierto)")

        logger.info("Buscando el boton 'Ver Ficha Ruc'...")
        boton_ficha = WebDriverWait(navegador.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "btnFichaRuc"))
        )
        try:
            boton_ficha.click()
        except Exception:
            navegador.driver.execute_script("arguments[0].click();", boton_ficha)

        logger.info("Clic en 'Ver Ficha Ruc' hecho, esperando a que cargue el contenido...")
        time.sleep(6)

        base_ficha = guardar_evidencia(navegador, empresa["ruc"], "03_ficha_ruc_en_iframe")
        archivos_generados.append(f"{base_ficha}.html")

        src_iframe = None
        try:
            iframe_el = navegador.driver.find_element(By.ID, "iframeApplication")
            src_iframe = iframe_el.get_attribute("src")
            navegador.driver.switch_to.frame(iframe_el)
            buscar_palabras_clave(navegador.driver, "03_ficha_ruc_en_iframe (dentro del iframe embebido)")

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            ruta_iframe_html = os.path.join(
                config.LOGS_DIR, f"diagnostico_ficha_ruc_{empresa['ruc']}_04_iframe_interno_{ts}.html"
            )
            with open(ruta_iframe_html, "w", encoding="utf-8") as f:
                f.write(navegador.driver.page_source)
            archivos_generados.append(ruta_iframe_html)
            logger.info(f"HTML interno del iframe guardado: {ruta_iframe_html}")
        except Exception as e:
            logger.warning(f"No se pudo leer el contenido interno del iframe: {e}")
        finally:
            navegador.driver.switch_to.default_content()

        # ---- Pregunta 1: PDF actual (pantalla intermedia) vs PDF despues
        # de hacer clic en el boton interno "Ficha RUC" ----
        if not src_iframe:
            logger.warning("No se pudo obtener el src del iframe, se salta toda la prueba de PDF.")
        else:
            ventana_original = navegador.driver.current_window_handle
            try:
                logger.info(f"Abriendo en pestaña nueva (esto es lo que genera produccion HOY): {src_iframe}")
                navegador.driver.execute_script("window.open(arguments[0], '_blank');", src_iframe)
                time.sleep(2)
                nueva_ventana = [w for w in navegador.driver.window_handles if w != ventana_original][-1]
                navegador.driver.switch_to.window(nueva_ventana)
                time.sleep(4)

                guardar_evidencia(navegador, empresa["ruc"], "05_pestana_nueva_ANTES_del_clic")
                buscar_palabras_clave(navegador.driver, "05_pestana_nueva_ANTES_del_clic (lo que genera produccion hoy)")
                ruta_pdf_v1 = generar_pdf(navegador.driver, empresa["ruc"], "v1_ANTES_del_clic")
                if ruta_pdf_v1:
                    archivos_generados.append(ruta_pdf_v1)

                # Ahora buscamos el boton interno "Ficha RUC" (el que el
                # usuario marco en la captura) y le hacemos clic.
                logger.info("Buscando el boton interno 'Ficha RUC' dentro de esta pestaña...")
                ventanas_antes_del_clic = set(navegador.driver.window_handles)
                boton_encontrado = False
                try:
                    boton_interno = WebDriverWait(navegador.driver, 8).until(
                        EC.presence_of_element_located((By.XPATH, XPATH_BOTON_FICHA_RUC_INTERNO))
                    )
                    logger.info(
                        f"Boton interno encontrado: tag={boton_interno.tag_name}, "
                        f"texto='{boton_interno.text}', id='{boton_interno.get_attribute('id')}', "
                        f"class='{boton_interno.get_attribute('class')}'"
                    )
                    try:
                        boton_interno.click()
                    except Exception:
                        navegador.driver.execute_script("arguments[0].click();", boton_interno)
                    boton_encontrado = True
                    time.sleep(4)
                except Exception as e:
                    logger.warning(
                        f"No se encontro (o no se pudo hacer clic en) el boton interno 'Ficha RUC' "
                        f"por el XPath probado: {e}. Revisa el HTML "
                        f"'05_pestana_nueva_ANTES_del_clic' para ver el boton real y ajustar el selector."
                    )

                if boton_encontrado:
                    # Si el clic abrio OTRA pestaña/ventana, nos cambiamos a
                    # esa; si no, asumimos que navego dentro de la misma.
                    ventanas_despues_del_clic = set(navegador.driver.window_handles)
                    ventanas_nuevas = ventanas_despues_del_clic - ventanas_antes_del_clic
                    if ventanas_nuevas:
                        logger.info("El clic abrio una pestaña/ventana nueva, cambiando a esa.")
                        navegador.driver.switch_to.window(list(ventanas_nuevas)[-1])
                        time.sleep(3)
                    else:
                        logger.info("El clic no abrio pestaña nueva -- se asume que navego en la misma.")

                    guardar_evidencia(navegador, empresa["ruc"], "06_pestana_DESPUES_del_clic")
                    buscar_palabras_clave(navegador.driver, "06_pestana_DESPUES_del_clic (la ficha deberia estar completa aca)")
                    ruta_pdf_v2 = generar_pdf(navegador.driver, empresa["ruc"], "v2_DESPUES_del_clic")
                    if ruta_pdf_v2:
                        archivos_generados.append(ruta_pdf_v2)

            except Exception as e:
                logger.error(f"Error en la prueba de PDF: {e}")
            finally:
                # Cierra todo lo que se haya abierto de mas y vuelve a la
                # ventana original del Menu SOL.
                try:
                    for w in navegador.driver.window_handles:
                        if w != ventana_original:
                            navegador.driver.switch_to.window(w)
                            navegador.driver.close()
                    navegador.driver.switch_to.window(ventana_original)
                except Exception as e:
                    logger.warning(f"No se pudo limpiar/volver a la ventana original: {e}")

        print("\n" + "=" * 70)
        print("LISTO. Comparte estos archivos para continuar (sobre todo los que")
        print("dicen '06_pestana_DESPUES_del_clic' y 'v2_DESPUES_del_clic'):")
        for ruta in archivos_generados:
            print(f"  {ruta}")
        print("=" * 70)

    finally:
        navegador.close_browser()
        display.stop()


if __name__ == "__main__":
    main()
