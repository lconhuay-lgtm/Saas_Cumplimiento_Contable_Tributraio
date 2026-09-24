#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de DIAGNOSTICO -- mide cuanto tiempo sigue siendo valido un ticket
de "ingreso directo" (accion_url/state/originalUrl, ver
core_scraper/adapter.py::preparar_ingreso_directo) despues de generado,
antes de que SUNAT lo rechace. Esto es justo lo que hace falta saber para
decidir si conviene "pre-calentar" el ingreso directo (dejar un ticket
listo en cache antes de que el usuario haga clic) y cuan generosa puede ser
esa ventana -- ver app/ingreso_directo_cache.py, que hoy usa un valor
conservador (45s) precisamente porque este numero todavia no se habia
medido.

VERSION 2 -- la primera version mandaba el POST con la libreria `requests`
(sin abrir navegador) y las 6 rondas fallaron TODAS con el mismo error de
conexion ("Remote end closed connection without response"), incluida la
ronda de delay=0s -- es decir, SUNAT (o algo delante, un WAF) esta
rechazando la conexion por como se ve el cliente (sin fingerprint de
navegador real: TLS, headers, etc.), no por el delay. Eso no mide nada util
sobre frescura, solo confirma que hace falta un navegador real para esta
prueba.

Por eso esta version NO usa `requests`: abre un Chrome real con Selenium
(igual que el resto del sistema), llega hasta la pantalla de login, y en
vez de cerrar esa pestaña, la deja ABIERTA durante el delay -- exactamente
como se queda abierta la pestaña real del usuario en produccion. Recien
despues del delay, inyecta con JavaScript (driver.execute_script) el MISMO
formulario oculto que arma _pagina_autoenvio_sunat en routers/empresas.py,
y lo envia DENTRO de esa misma pestaña. Asi el delay queda aislado como la
UNICA variable que cambia entre rondas -- el navegador/TLS/headers son
identicos a los de produccion en todos los casos.

Hace REAL logins en SUNAT (con las credenciales reales de una empresa que
ya tengas guardada -- por defecto la que este marcada como "cuenta
canario"). No escribe nada distinto a lo que ya hace un login normal.

Como correrlo (PowerShell, desde la carpeta buzon-saas):
    docker-compose exec worker python diagnosticar_frescura_ingreso_directo.py [RUC opcional]

Tarda unos 8-10 minutos en total (6 rondas, cada una con su propia espera
mas el tiempo de abrir/cerrar el navegador). El resultado queda tambien
impreso al final: el delay mas grande que SIGUIO funcionando es la pista
para ajustar DEFAULT_MAX_EDAD_SEG en app/ingreso_directo_cache.py.
"""
import os
import sys
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urljoin

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as core_config  # config.py de core_scraper (ya esta en PYTHONPATH)
core_config.setup_logging()

import logging
logger = logging.getLogger("diagnosticar_frescura_ingreso_directo")

from pyvirtualdisplay import Display

from app.database import SessionLocal
from app.models import Empresa, CredencialSol
from app.security import descifrar_clave_sol

from web_navigation import SunatWebNavigator
import config

# Delays en segundos a probar, de menor a mayor -- si uno falla, los
# siguientes (mas largos) casi seguro tambien van a fallar, pero se
# prueban igual para tener el cuadro completo en el log.
DELAYS_A_PROBAR = [0, 20, 40, 60, 90, 120]


def obtener_empresa_de_prueba(ruc: str | None):
    """
    Igual que en diagnostico_ficha_ruc.py, pero prioriza la cuenta
    canario (Empresa.es_canario=True) cuando no se pide un RUC puntual --
    es la cuenta pensada justamente para este tipo de pruebas repetidas.
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
            query = query.order_by(Empresa.es_canario.desc(), Empresa.creado_en.desc())
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
                "es_canario": empresa.es_canario,
            }

        sys.exit("Ninguna de las empresas candidatas tiene una credencial que se pueda descifrar.")
    finally:
        db.close()


def evaluar_resultado_url(url_final: str) -> tuple[bool | None, str]:
    """
    Heuristica sobre a donde termino la pestaña despues de enviar el
    formulario: exitoso = termino en el dominio del Menu SOL
    (e-menu.sunat.gob.pe) y NO de vuelta en la pantalla de login. Si no
    calza ninguno de los dos patrones esperados, se marca como INCIERTO --
    ahi hay que mirar el HTML de evidencia guardado para decidir a mano.
    """
    if "e-menu.sunat.gob.pe" in url_final and "loginMenuSol" not in url_final:
        return True, f"EXITO -- termino en el Menu SOL: {url_final}"
    if "loginMenuSol" in url_final or "api-seguridad.sunat.gob.pe" in url_final:
        return False, f"RECHAZADO -- SUNAT lo devolvio a la pantalla de login: {url_final}"
    return None, f"INCIERTO -- URL final no reconocida, revisar el HTML de evidencia: {url_final}"


def probar_un_delay(empresa: dict, delay_seg: int) -> dict:
    logger.info(f"--- Ronda delay={delay_seg}s: abriendo un navegador real y llegando al login ---")

    navegador = SunatWebNavigator(empresa=None, headless=False)
    try:
        if not navegador.initialize_browser():
            return {"delay": delay_seg, "resultado": None, "detalle": "No se pudo iniciar el navegador"}

        navegador.driver.get(config.URL_SUNAT)
        url_login = navegador.obtener_url_login()
        if not url_login:
            return {"delay": delay_seg, "resultado": None, "detalle": "No se pudo llegar a la pantalla de login"}

        partes = urlparse(url_login)
        query = parse_qs(partes.query)
        state = query.get("state", [None])[0]
        original_url = query.get("originalUrl", [None])[0]
        lang = query.get("lang", ["es-PE"])[0]
        accion_url = urljoin(url_login, "j_security_check")

        logger.info(
            f"Ticket generado. Esperando {delay_seg}s CON LA MISMA PESTAÑA ABIERTA "
            "(igual que se queda abierta la pestaña real del usuario en produccion)..."
        )
        time.sleep(delay_seg)

        logger.info(f"Enviando el formulario (delay={delay_seg}s) DENTRO de ese mismo navegador real...")
        js_envio = """
        var datos = arguments[0];
        var f = document.createElement('form');
        f.method = 'POST';
        f.action = datos.accion_url;
        Object.keys(datos.campos).forEach(function(nombre) {
            var i = document.createElement('input');
            i.type = 'hidden';
            i.name = nombre;
            i.value = datos.campos[nombre];
            f.appendChild(i);
        });
        document.body.appendChild(f);
        f.submit();
        """
        datos_formulario = {
            "accion_url": accion_url,
            "campos": {
                "tipo": "2",
                "dni": "",
                "custom_ruc": empresa["ruc"],
                "j_username": empresa["usuario"],
                "j_password": empresa["clave"],
                "captcha": "",
                "originalUrl": original_url or "",
                "lang": lang or "es-PE",
                "state": state or "",
            },
        }
        navegador.driver.execute_script(js_envio, datos_formulario)
        time.sleep(5)  # esperar a que la pagina redireccione/termine de cargar

        url_final = navegador.driver.current_url
        exito, detalle = evaluar_resultado_url(url_final)
        logger.info(f"[delay={delay_seg}s] {detalle}")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta_evidencia = os.path.join(core_config.LOGS_DIR, f"frescura_ingreso_directo_delay{delay_seg}s_{ts}.html")
        try:
            with open(ruta_evidencia, "w", encoding="utf-8") as f:
                f.write(navegador.driver.page_source)
            logger.info(f"[delay={delay_seg}s] HTML guardado en: {ruta_evidencia}")
        except Exception as e:
            logger.warning(f"No se pudo guardar la evidencia HTML: {e}")

        return {"delay": delay_seg, "resultado": exito, "detalle": detalle, "evidencia": ruta_evidencia}

    except Exception as e:
        logger.error(f"Error inesperado en la ronda delay={delay_seg}s: {e}")
        return {"delay": delay_seg, "resultado": None, "detalle": f"Error inesperado: {e}"}
    finally:
        navegador.close_browser()


def main():
    ruc_pedido = sys.argv[1].strip() if len(sys.argv) > 1 else None
    empresa = obtener_empresa_de_prueba(ruc_pedido)
    etiqueta_cuenta = "cuenta canario" if empresa.get("es_canario") else "empresa (NO es la cuenta canario)"
    logger.info(f"Usando {etiqueta_cuenta}: {empresa['ruc']} - {empresa['razon_social']}")
    if not empresa.get("es_canario"):
        logger.warning(
            "OJO: esta prueba va a hacer varios logins reales seguidos contra esta cuenta. "
            "Si preferis usar la cuenta canario, correla sin argumentos (la elige automatico) "
            "o marca una empresa como canario primero."
        )

    # Esto corre como un proceso NUEVO de `docker-compose exec worker ...`
    # -- NO hereda el DISPLAY que worker_entry.py arranca para si mismo en
    # el proceso principal del contenedor (esa variable de entorno vive
    # solo dentro de ESE proceso, no queda "puesta" para el contenedor en
    # general). Mismo motivo y mismo patron que diagnostico_ficha_ruc.py:
    # arranca su propia pantalla virtual antes de abrir cualquier Chrome.
    logger.info("Arrancando pantalla virtual (Xvfb) para las rondas de descubrimiento...")
    display = Display(visible=False, size=(1600, 1000))
    display.start()

    resultados = []
    try:
        for delay in DELAYS_A_PROBAR:
            resultados.append(probar_un_delay(empresa, delay))
    finally:
        display.stop()

    print("\n" + "=" * 70)
    print(f"RESUMEN -- frescura del ticket de ingreso directo ({empresa['ruc']})")
    print("=" * 70)
    ultimo_delay_exitoso = None
    for r in resultados:
        estado = "EXITO   " if r["resultado"] is True else "RECHAZO " if r["resultado"] is False else "INCIERTO"
        print(f"  delay={r['delay']:>4}s  ->  {estado}  {r['detalle']}")
        if r["resultado"] is True:
            ultimo_delay_exitoso = r["delay"]
    print("=" * 70)
    if ultimo_delay_exitoso is not None:
        print(
            f"El ticket siguio siendo aceptado hasta al menos {ultimo_delay_exitoso} segundos despues de "
            "generado. Con ese dato se puede ajustar DEFAULT_MAX_EDAD_SEG en "
            "backend/app/ingreso_directo_cache.py (dejarlo con margen, no al limite exacto)."
        )
    else:
        print(
            "Ningun delay probado resulto EXITO claro -- revisa los .html de evidencia listados arriba "
            "(carpeta sunat_data/logs/) antes de tocar nada del cache."
        )
    print("=" * 70)


if __name__ == "__main__":
    main()
