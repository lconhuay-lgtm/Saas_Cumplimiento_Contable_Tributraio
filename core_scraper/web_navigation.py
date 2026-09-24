#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Módulo para la navegación web en el portal de SUNAT utilizando Selenium.
Este módulo se encarga de todas las interacciones con el navegador web:
- Inicialización del navegador
- Autenticación en el portal SUNAT
- Navegación por las diferentes secciones
- Descarga de documentos
- Manejo de esperas y excepciones
"""
import os
import time
import logging
import re
from datetime import datetime, timedelta
import shutil


from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, 
    NoSuchElementException, 
    ElementClickInterceptedException,
    StaleElementReferenceException
)
from config import CHROME_PREFS

# Importar módulos propios
import config
from data_access import crear_estructura_carpetas, mover_archivo_descargado

# Configurar logger
logger = logging.getLogger('web_navigation')

class SunatWebNavigator:
    """
    Clase para manejar la navegación web en el portal de SUNAT.
    """
    def __init__(self, empresa=None, headless=False):
        """
        Inicializa el navegador web y configura las opciones.
        
        Args:
            empresa (dict, optional): Información de la empresa (RUC, razón social, etc.)
            headless (bool): Si se ejecuta el navegador en modo headless (sin interfaz gráfica).
        """
        self.driver = None
        self.empresa = empresa
        self.headless = headless
        self.wait = None
        self.download_dir = None
        # Nombre real que SUNAT le reconoce al RUC logueado (leido del banner
        # "Bienvenido, ..." del Menu SOL tras el login) -- puede diferir del
        # nombre que el usuario escribio a mano o del que trae un Excel
        # importado, que a veces tiene errores de tipeo.
        self.razon_social_detectada = None
        # Condicion del domicilio fiscal (Habido / No Habido / No Hallado),
        # leida del mismo navbar del Menu SOL -- relevante porque afecta la
        # declaracion de impuestos de la empresa.
        self.condicion_domicilio_detectada = None
        # Estado del contribuyente (Activo / Baja de Oficio / etc.), leido
        # DENTRO de la Ficha RUC (no aparece en el navbar normal, ver
        # _leer_estado_contribuyente) -- tambien afecta la declaracion de
        # impuestos de la empresa.
        self.estado_contribuyente_detectado = None
        # "flujo1" | "flujo2" | "sin_flujo" -- que pantalla post-login
        # mostro SUNAT en esta sesion (ver _click_condicional). Fase 3:
        # se usa para el chequeo canario, como señal temprana de que SUNAT
        # esta cambiando su portal (la distribucion de estos valores puede
        # cambiar antes de que algo se rompa del todo). None hasta que
        # _click_condicional corre.
        self.flujo_detectado = None

    def initialize_browser(self):
        """
        Inicializa el navegador Chrome con las configuraciones adecuadas.
        """
        try:
            options = webdriver.ChromeOptions()

            # En Docker/Linux, apuntar explicitamente al binario de Chromium si
            # la variable de entorno esta configurada (en Windows queda vacia y
            # no cambia nada del comportamiento original).
            if config.CHROME_BINARY_LOCATION:
                options.binary_location = config.CHROME_BINARY_LOCATION

            # Configurar carpeta de descargas
            if self.empresa:
                self.download_dir = crear_estructura_carpetas(self.empresa)
            else:
                self.download_dir = config.BASE_DIR
                
            logger.info(f"Carpeta de descargas configurada: {self.download_dir}")
            
            # Configuración MEJORADA para descargas automáticas
            prefs = {
                "download.default_directory": self.download_dir,
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True,
                "plugins.always_open_pdf_externally": True,
                # NUEVAS CONFIGURACIONES PARA FORZAR DESCARGA AUTOMÁTICA
                "plugins.plugins_disabled": ["Chrome PDF Viewer"],
                "download.extensions_to_open": "",
                "download.open_pdf_in_system_reader": False,
                "profile.default_content_settings.popups": 0,
                "profile.default_content_setting_values.automatic_downloads": 1,
                "profile.content_settings.exceptions.automatic_downloads.*.setting": 1,
                # Evitar diálogos de contraseña
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False
            }
            options.add_experimental_option("prefs", prefs)
            
            # Agregar argumentos adicionales MEJORADOS
            chrome_args = [
                '--disable-popup-blocking',
                '--disable-notifications',
                '--disable-extensions',
                '--no-sandbox',
                '--disable-gpu',
                '--guest',
                # NUEVOS ARGUMENTOS PARA DESCARGAS
                '--disable-web-security',
                '--allow-running-insecure-content',
                '--disable-features=VizDisplayCompositor',
                '--disable-features=TranslateUI',
                '--disable-iframes-during-reload',
                '--disable-background-timer-throttling',
                '--disable-renderer-backgrounding',
                '--disable-backgrounding-occluded-windows'
            ]
            
            for opcion in chrome_args:
                options.add_argument(opcion)
                
            if self.headless:
                options.add_argument("--headless=new")
                # CRITICO: en headless, Chrome no "maximiza" a un tamaño real
                # (no hay pantalla) -- sin esto el viewport queda chico por
                # defecto, SUNAT activa su diseno "movil" (menu hamburguesa),
                # los elementos se superponen y los clics fallan con
                # ElementClickInterceptedException. Mismo problema que ya
                # habiamos resuelto para la ventana visible, pero headless
                # tiene su propio camino y no pasaba por ahi.
                options.add_argument("--window-size=1600,1000")

            # Si hay un chromedriver ya instalado en el sistema (caso tipico
            # de Docker/Linux, instalado via apt junto con Chromium), usarlo
            # directamente evita depender de que ChromeDriverManager pueda
            # descargar algo en tiempo de ejecucion.
            if config.CHROMEDRIVER_PATH:
                try:
                    logger.info(f"Usando chromedriver del sistema: {config.CHROMEDRIVER_PATH}")
                    self.driver = webdriver.Chrome(
                        service=Service(config.CHROMEDRIVER_PATH),
                        options=options
                    )
                except Exception as e:
                    logger.warning(f"Error con chromedriver del sistema: {str(e)}")
                    self.driver = None
            else:
                self.driver = None

            if self.driver is None:
                try:
                    # Método 1: Intentar instalar automáticamente el ChromeDriver
                    logger.info("Intentando inicializar el driver con ChromeDriverManager...")
                    self.driver = webdriver.Chrome(
                        service=Service(ChromeDriverManager().install()),
                        options=options
                    )
                except Exception as e:
                    logger.warning(f"Error con ChromeDriverManager: {str(e)}")
                    try:
                        # Método 2: Usar el ChromeDriver instalado localmente
                        logger.info("Intentando inicializar el driver con el ChromeDriver local...")
                        self.driver = webdriver.Chrome(options=options)
                    except Exception as e2:
                        logger.error(f"Error al inicializar con ChromeDriver local: {str(e2)}")
                        raise
            
            # Configurar el tiempo de espera predeterminado
            self.wait = WebDriverWait(self.driver, config.TIEMPO_ESPERA_DEFAULT)
            try:
                self.driver.maximize_window()
            except Exception as e:
                # Dentro de Xvfb (pantalla virtual sin gestor de ventanas)
                # maximize_window() puede fallar con "unknown command:
                # 'Runtime.evaluate' wasn't found" -- es un problema conocido
                # de Chrome/Selenium cuando no hay un window manager real
                # atendiendo la ventana. No es grave: mas abajo,
                # _ocultar_ventana_si_corresponde() fija un tamaño explicito
                # de 1600x1000 de todas formas, asi que seguimos sin maximizar.
                logger.warning(f"No se pudo maximizar la ventana (se seguira con tamaño explicito mas adelante): {str(e)}")

            # NUEVO: Configurar descargas automáticas via JavaScript
            self.driver.execute_cdp_cmd('Page.setDownloadBehavior', {
                'behavior': 'allow',
                'downloadPath': self.download_dir
            })

            # Sacar la ventana fuera del area visible de la pantalla para que
            # no interrumpa el trabajo del usuario. Se usa reposicionamiento
            # (no minimizar) porque Chrome "pausa"/ralentiza las pestañas
            # minimizadas (deja de renderizar y limita temporizadores), lo
            # que puede hacer fallar los clics de la automatizacion. Al
            # reposicionar la ventana fuera de la pantalla en vez de
            # minimizarla, Chrome la sigue tratando como visible y la
            # automatizacion funciona igual de confiable que con la ventana
            # visible, solo que el usuario no la ve ni pierde el foco de su
            # propio trabajo.
            self._ocultar_ventana_si_corresponde()

            logger.info("Navegador inicializado correctamente")
            return True

        except Exception as e:
            logger.error(f"Error al inicializar el navegador: {str(e)}")
            return False

    def _ocultar_ventana_si_corresponde(self):
        """
        Reposiciona la ventana del navegador fuera del area visible de la
        pantalla (si no se esta corriendo en modo headless), en lugar de
        minimizarla, para evitar que Chrome limite el rendimiento de la
        pestaña. SUNAT abre/cierra varias ventanas durante el login y la
        navegacion, y cada cambio de ventana (switch_to.window) puede volver
        a mostrarla en pantalla, asi que este metodo se llama despues de cada
        cambio de ventana para mantenerla fuera de la vista del usuario.
        """
        if self.headless:
            return
        try:
            # Fijar un tamaño grande explícito (no solo reposicionar) porque
            # algunas ventanas nuevas que abre SUNAT durante el login no
            # quedan maximizadas por defecto; si la ventana queda chica,
            # SUNAT muestra su diseño "móvil" (menú hamburguesa) y oculta
            # enlaces como "Buzón Electrónico", rompiendo la navegación.
            self.driver.set_window_size(1600, 1000)
            self.driver.set_window_position(-3000, 0)
        except Exception as e:
            logger.warning(f"No se pudo reposicionar la ventana del navegador: {str(e)}")

    def close_browser(self):
        """
        Cierra el navegador y libera los recursos.
        """
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Navegador cerrado correctamente")
            except Exception as e:
                logger.error(f"Error al cerrar el navegador: {str(e)}")
                
    def ejecutar_proceso_completo(self, empresa, max_intentos=None, dias_atras=1):
        """
        Ejecuta el proceso completo para una empresa específica.
        
        Args:
            empresa (dict): Información de la empresa
            max_intentos (int): Número máximo de intentos
            dias_atras (int): Número de días atrás a considerar para procesar mensajes
                
        Returns:
            bool: True si el proceso fue exitoso, False en caso contrario
        """
        if max_intentos is None:
            max_intentos = config.MAX_INTENTOS
                
        self.empresa = empresa
        logger.info(f"Iniciando proceso para empresa: {empresa['ruc']} - {empresa.get('razon_social', '')}")
        
        for intento in range(max_intentos):
            try:
                logger.info(f"Iniciando intento {intento + 1} de {max_intentos}")
                
                # Inicializar navegador
                if not self.initialize_browser():
                    logger.error("Error al inicializar el navegador")
                    continue
                
                try:
                    # Navegar a la página principal de SUNAT
                    self.driver.get(config.URL_SUNAT)
                    logger.info("Página principal de SUNAT cargada exitosamente")
                    time.sleep(3)
                    
                    # Realizar la navegación inicial
                    if not self._hacer_clicks_sunat(empresa):
                        logger.error(f"Error en el proceso de navegación inicial - Intento {intento + 1}")
                        self.close_browser()
                        continue
                    
                    # Navegar al Buzón de Notificaciones
                    if not self._navegar_a_buzon_notificaciones():
                        logger.error(f"Error al navegar al Buzón de Notificaciones - Intento {intento + 1}")
                        self.close_browser()
                        continue
                    
                    # Procesar mensajes del periodo configurado (hoy + días atrás)
                    resultado, mensaje = self._procesar_mensajes_periodo(dias_atras, max_intentos)
                    
                    if resultado:
                        logger.info(f"Proceso exitoso: {mensaje}")
                        self.close_browser()
                        return True
                    else:
                        logger.warning(f"{mensaje} - Intento {intento + 1}")
                        self.close_browser()
                        continue
                    
                except Exception as e:
                    logger.error(f"Error durante el intento {intento + 1}: {str(e)}")
                    self.close_browser()
                    continue
                    
            except Exception as e:
                logger.error(f"Error al iniciar el navegador en intento {intento + 1}: {str(e)}")
                try:
                    self.close_browser()
                except:
                    pass
                continue
        
        logger.error(f"Proceso fallado después de {max_intentos} intentos para {empresa['ruc']}")
        return False
    
    def _clicks_hasta_login(self, rapido=False):
        """
        Los 2 clics iniciales de la portada de SUNAT (www.sunat.gob.pe) hasta
        llegar a la pantalla de login -- compartido entre el flujo de login
        normal (_hacer_clicks_sunat, que sigue e ingresa credenciales) y
        obtener_url_login() (que se DETIENE aca, sin ingresar nada, para el
        ingreso directo -- ver adapter.py::preparar_ingreso_directo). Antes
        vivia duplicado dentro de _hacer_clicks_sunat; se extrajo para que
        ambos flujos usen exactamente los mismos selectores.

        Args:
            rapido (bool): si True, saca las esperas FIJAS (time.sleep) que
                estaban ahi solo de colchon extra, ademas de las esperas
                EXPLICITAS de Selenium (wait.until clickable/presente, que
                se mantienen exactamente igual y siguen esperando con
                polling lo que haga falta -- no es que se deje de esperar,
                es que se deja de esperar a CIEGAS de mas). Pensado
                UNICAMENTE para obtener_url_login() (Ingreso Directo),
                donde la meta es solo llegar a la pantalla de login lo
                antes posible. _hacer_clicks_sunat (usado por el chequeo
                canario, las consultas normales y la Ficha RUC) sigue
                llamando con rapido=False, con el timing identico a como
                estaba -- cero riesgo de regresion ahi.

        Returns:
            bool: True si se llego a la pantalla de login (ventana correcta
            activa), False en caso contrario.
        """
        # Primer click
        xpath_primer_boton = "/html/body/section[3]/div[2]/div[1]/a/span[2]"

        elemento = self.wait.until(
            EC.presence_of_element_located((By.XPATH, xpath_primer_boton))
        )

        self.driver.execute_script("window.scrollBy(0, 350);")
        if not rapido:
            time.sleep(1)

        boton = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, xpath_primer_boton))
        )
        try:
            boton.click()
        except Exception as e:
            # SUNAT agrego un widget de chat flotante ("Pregúntale a
            # Sofía") que a veces queda encima de este boton e intercepta
            # el clic (ElementClickInterceptedException). El clic via
            # JavaScript no pasa por la capa visual de la pagina, asi
            # que ignora ese overlay -- mismo patron ya usado en otros
            # clics de este archivo.
            logger.warning(f"Clic normal fallo en primer boton, probando con JavaScript: {str(e)}")
            self.driver.execute_script("arguments[0].click();", boton)
        logger.info("Primer clic exitoso")

        if not rapido:
            time.sleep(5)

        # Segundo click
        xpath_segundo_boton = "/html/body/section[1]/div/div/section[2]/div[2]/div/a/span"
        segundo_boton = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, xpath_segundo_boton))
        )
        try:
            segundo_boton.click()
        except Exception as e:
            logger.warning(f"Clic normal fallo en segundo boton, probando con JavaScript: {str(e)}")
            self.driver.execute_script("arguments[0].click();", segundo_boton)
        logger.info("Segundo clic exitoso")

        # Cerrar la ventana de comunicado
        return self._cerrar_ventana_comunicado(rapido=rapido)

    def obtener_url_login(self):
        """
        Llega hasta la pantalla de login de SUNAT (los mismos 2 clics de
        siempre) pero se DETIENE ahi -- sin ingresar ningun RUC/usuario/
        clave -- y devuelve la URL exacta de esa pantalla.

        Para que sirve: la URL de login incluye un parametro `state` (y
        `originalUrl`) que SUNAT genera de nuevo en cada sesion -- son
        justo los valores que hacen falta para armar, en el backend, un
        formulario que se autoenvia en el navegador REAL del usuario (ver
        adapter.py::preparar_ingreso_directo) y lo deja logueado en una
        pestaña autentica de SUNAT sin escribir nada. No tiene sentido
        cachear esta URL -- hay que pedirla de nuevo cada vez.

        Returns:
            str | None: la URL completa de la pantalla de login (con sus
            query params originales), o None si no se pudo llegar hasta ahi.
        """
        try:
            if not self._clicks_hasta_login(rapido=True):
                logger.warning("No se pudo manejar correctamente las ventanas (obtener_url_login)")
                return None

            url_login = self.driver.current_url
            logger.info(f"URL de login obtenida para ingreso directo: {url_login}")
            return url_login

        except Exception as e:
            logger.error(f"Error al obtener la URL de login: {str(e)}")
            self._guardar_captura_error("obtener_url_login")
            return None

    def _hacer_clicks_sunat(self, empresa):
        """
        Realiza los clicks iniciales en la página de SUNAT y el proceso de login.

        Args:
            empresa (dict): Información de la empresa

        Returns:
            bool: True si el proceso fue exitoso, False en caso contrario
        """
        try:
            if not self._clicks_hasta_login():
                logger.warning("No se pudo manejar correctamente las ventanas")
                return False

            # Ingresar credenciales
            if not self._ingresar_credenciales(empresa):
                logger.error("Error al ingresar las credenciales")
                return False

            # Leer el nombre real que SUNAT reconoce para este RUC (para
            # mantener actualizada la razon social guardada) y la condicion
            # del domicilio fiscal. Se hace aca, apenas se confirma el
            # login, porque ambos estan disponibles en esta pantalla y
            # desaparecen de foco mas adelante en la navegacion.
            self.razon_social_detectada = self._detectar_razon_social()
            self.condicion_domicilio_detectada = self._detectar_condicion_domicilio()

            # Manejar los modales después del login
            if not self._click_condicional():
                logger.error("Error en el proceso de clicks modales")
                return False

            return True

        except Exception as e:
            logger.error(f"Error durante la navegación: {str(e)}")
            self._guardar_captura_error("hacer_clicks_sunat")
            return False

    def _guardar_captura_error(self, etiqueta):
        """Guarda una captura de pantalla + el HTML de la pagina en el momento del error, para diagnosticar sin ver la sesion en vivo (headless/worker)."""
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            base = os.path.join(config.LOGS_DIR, f"error_{etiqueta}_{ts}")
            self.driver.save_screenshot(f"{base}.png")
            with open(f"{base}.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            logger.error(f"Diagnostico guardado: {base}.png / {base}.html (URL: {self.driver.current_url})")
        except Exception as e2:
            logger.warning(f"No se pudo guardar la captura de diagnostico: {str(e2)}")

    def _cerrar_ventana_comunicado(self, rapido=False):
        """
        Cierra ventanas emergentes de comunicados o avisos.

        Args:
            rapido (bool): si True, en vez de una espera fija de 2s, espera
                ACTIVAMENTE (como maximo 5s) a que aparezca la segunda
                ventana -- si esta vez SUNAT no muestra ningun comunicado,
                sigue de largo sin penalizar el tiempo total igual. Ver
                _clicks_hasta_login para el detalle de por que existe esto.

        Returns:
            bool: True si se cerró correctamente, False en caso contrario
        """
        try:
            if rapido:
                try:
                    WebDriverWait(self.driver, 5).until(EC.number_of_windows_to_be(2))
                except TimeoutException:
                    pass
            else:
                time.sleep(2)
            ventanas = self.driver.window_handles
            ventana_principal = ventanas[0]
            ventana_a_mantener = None
            
            for ventana in ventanas:
                self.driver.switch_to.window(ventana)
                self._ocultar_ventana_si_corresponde()
                if ("COMUNICADO" in self.driver.title or
                    "mensajes" in self.driver.current_url or
                    "aviso" in self.driver.current_url):
                    logger.info(f"Ventana de comunicado encontrada: {self.driver.title}")
                    self.driver.close()
                else:
                    ventana_a_mantener = ventana

            if ventana_a_mantener:
                self.driver.switch_to.window(ventana_a_mantener)
                self._ocultar_ventana_si_corresponde()
                logger.info("Cambiado a la ventana principal de SUNAT")
                return True
                
            return False
        
        except Exception as e:
            logger.error(f"Error al cerrar ventana de comunicado: {str(e)}")
            return False
            
    def _ingresar_credenciales(self, empresa):
        """
        Ingresa las credenciales de la empresa en el formulario de login.
        
        Args:
            empresa (dict): Información de la empresa
            
        Returns:
            bool: True si el ingreso fue exitoso, False en caso contrario
        """
        try:
            # Extraer credenciales de la empresa
            ruc = empresa['ruc']
            usuario = empresa['usuario']
            clave = empresa['clave']
            
            logger.info(f"Ingresando credenciales para {ruc} - {empresa.get('razon_social', '')}")
            
            # Esperar y llenar RUC
            xpath_ruc = "/html/body/div[2]/div/div/div/div[2]/div/form/div[3]/input"
            campo_ruc = self.wait.until(
                EC.presence_of_element_located((By.XPATH, xpath_ruc))
            )
            campo_ruc.clear()
            campo_ruc.send_keys(ruc)
            logger.info("RUC ingresado correctamente")
            
            # Esperar y llenar Usuario
            xpath_usuario = "/html/body/div[2]/div/div/div/div[2]/div/form/div[4]/input"
            campo_usuario = self.wait.until(
                EC.presence_of_element_located((By.XPATH, xpath_usuario))
            )
            campo_usuario.clear()
            campo_usuario.send_keys(usuario)
            logger.info("Usuario ingresado correctamente")
            
            # Esperar y llenar Contraseña
            xpath_password = "/html/body/div[2]/div/div/div/div[2]/div/form/div[5]/input"
            campo_password = self.wait.until(
                EC.presence_of_element_located((By.XPATH, xpath_password))
            )
            campo_password.clear()
            campo_password.send_keys(clave)
            logger.info("Contraseña ingresada correctamente")
            
            # Esperar y hacer click en el botón de inicio de sesión
            xpath_boton_login = "/html/body/div[2]/div/div/div/div[2]/div/form/div[10]/button"
            boton_login = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, xpath_boton_login))
            )
            boton_login.click()
            logger.info("Click en botón de inicio de sesión exitoso")
            
            # Esperar un momento después del login
            time.sleep(3)
            try:
                self.driver.maximize_window()
            except Exception as e:
                # Mismo problema conocido de Xvfb sin gestor de ventanas que
                # en initialize_browser() -- no es grave, el tamaño explicito
                # de _ocultar_ventana_si_corresponde() alcanza igual.
                logger.warning(f"No se pudo maximizar la ventana tras el login (se seguira con tamaño explicito): {str(e)}")
            self._ocultar_ventana_si_corresponde()

            return True
            
        except Exception as e:
            logger.error(f"Error al ingresar credenciales: {str(e)}")
            self._guardar_captura_error("ingresar_credenciales")
            return False

    def _detectar_razon_social(self):
        """
        Lee el nombre que SUNAT le reconoce al RUC de la sesion actual,
        tomado del banner "Bienvenido, {nombre}" que aparece en la esquina
        superior derecha del Menu SOL justo despues de iniciar sesion
        (elemento #aOpcionUsuario2 -- confirmado con una captura real de
        produccion). Se usa para mantener la razon social guardada en la
        base de datos igual a la oficial de SUNAT, en vez de depender de lo
        que el usuario escribio a mano o de una columna de un Excel
        importado (que puede tener errores de tipeo).

        Nunca debe tumbar el login si falla: es informativo, no
        imprescindible para llegar al Buzon Electronico.

        Returns:
            str | None: el nombre detectado, o None si no se pudo leer.
        """
        try:
            elemento = WebDriverWait(self.driver, 8).until(
                EC.presence_of_element_located((By.ID, "aOpcionUsuario2"))
            )
            texto = (elemento.text or "").strip()
            # El elemento trae "Bienvenido, NOMBRE DE LA EMPRESA" en dos
            # <span> separados pero .text los junta con un salto de linea o
            # coma segun el caso -- se corta en la primera coma si la hay,
            # si no se usa el texto completo tal cual.
            if "," in texto:
                nombre = texto.split(",", 1)[1].strip()
            else:
                nombre = texto.strip()
            # Fallback por si el texto vino sin la palabra "Bienvenido"
            # delante (algun cambio menor de SUNAT) -- se intenta leer el
            # segundo <span> directamente.
            if not nombre or nombre.lower().startswith("bienvenido"):
                spans = elemento.find_elements(By.TAG_NAME, "span")
                textos_span = [s.text.strip() for s in spans if s.text.strip()]
                candidatos = [t for t in textos_span if "bienvenido" not in t.lower() and t != "caret"]
                nombre = candidatos[0] if candidatos else ""

            if nombre:
                logger.info(f"Razon social detectada en la sesion de SUNAT: '{nombre}'")
                return nombre
            logger.warning(f"Banner de bienvenida encontrado pero sin nombre reconocible: '{texto}'")
            return None
        except Exception as e:
            logger.warning(f"No se pudo detectar la razon social desde la sesion de SUNAT (no es grave, se sigue con el nombre ya guardado): {str(e)}")
            return None

    def _detectar_condicion_domicilio(self):
        """
        Lee la condicion del domicilio fiscal (Habido / No Habido / No
        Hallado) que SUNAT muestra en el navbar del Menu SOL, justo al lado
        del nombre de la empresa (elemento .spanEstadoDomicilio --
        confirmado con una captura real de produccion, misma pantalla que
        el banner "Bienvenido"). Afecta la declaracion de impuestos de la
        empresa, por eso vale la pena mostrarlo.

        SUNAT repite este elemento DOS veces en el navbar: una copia para
        pantallas moviles (oculta con clases hidden-sm/hidden-md/hidden-lg
        en cualquier pantalla que no sea chica) y otra para escritorio. Con
        By.CLASS_NAME, Selenium devuelve la PRIMERA que aparece en el DOM,
        que resulta ser la version movil -- invisible en el tamaño de
        pantalla que usa este bot (1600x1000), y el .text de un elemento
        oculto siempre es cadena vacia. Eso hacia que esta funcion devolviera
        None en produccion aunque el dato si estaba en la pagina (bug real,
        confirmado con diagnostico_ficha_ruc.py). Se recorren TODAS las
        copias y se usa la primera que este realmente visible.

        Nunca debe tumbar el login si falla: es informativo.

        Returns:
            str | None: "Habido", "No Habido", "No Hallado", etc. segun lo
            que SUNAT muestre textualmente, o None si no se pudo leer.
        """
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CLASS_NAME, "spanEstadoDomicilio"))
            )
            for elemento in self.driver.find_elements(By.CLASS_NAME, "spanEstadoDomicilio"):
                try:
                    if not elemento.is_displayed():
                        continue
                    texto = (elemento.text or "").strip()
                    if texto:
                        logger.info(f"Condicion de domicilio detectada en la sesion de SUNAT: '{texto}'")
                        return texto
                except Exception:
                    continue
            logger.warning("Se encontro el elemento de condicion de domicilio pero ninguna copia visible tenia texto")
            return None
        except Exception as e:
            logger.warning(f"No se pudo detectar la condicion de domicilio desde la sesion de SUNAT (no es grave): {str(e)}")
            return None

    def _leer_estado_contribuyente(self):
        """
        Entra a la "Ficha RUC" SOLO para leer el "Estado del Contribuyente"
        (Activo / Baja de Oficio / Baja Provisional / Suspension Temporal,
        etc.) -- a diferencia de la razon social y la condicion de
        domicilio, este dato NO aparece en el navbar normal del Menu SOL.
        Confirmado con un diagnostico real (ver diagnostico_ficha_ruc.py):
        buscando las mismas palabras clave en el banner "Bienvenido" y en
        el desplegable del nombre solo aparecia "HABIDO" (la condicion de
        domicilio); "ACTIVO" y "ESTADO DEL CONTRIBUYENTE" solo aparecian
        DENTRO del iframe de la Ficha RUC. Afecta directamente la
        declaracion de impuestos (una "baja de oficio" implica que la
        empresa ya no deberia estar declarando), por eso vale la pena
        pagar el costo extra (unos 8-10 segundos) de entrar a buscarlo en
        cada consulta -- a diferencia de generar el PDF completo de la
        Ficha RUC, que sigue siendo solo bajo pedido explicito del usuario
        porque ese si es mucho mas lento (abre una pestaña aparte y genera
        el PDF via Chrome DevTools).

        A diferencia de _detectar_razon_social/_detectar_condicion_domicilio
        (que solo LEEN lo que ya esta en pantalla), esta funcion SI navega:
        abre el desplegable del nombre, hace clic en "Ver Ficha Ruc", lee
        el iframe, y vuelve al contexto principal. Un fallo aca nunca debe
        tumbar el resto de la consulta -- _navegar_a_buzon_notificaciones
        (que se llama justo despues) siempre arranca con su propio
        switch_to.default_content() y es tolerante a iframes/overlays
        sueltos, asi que en el peor caso solo se pierde este dato puntual.

        Returns:
            str | None: el texto tal cual lo muestra SUNAT ("ACTIVO",
            "BAJA DE OFICIO", etc.), o None si no se pudo leer.
        """
        try:
            boton_nombre = WebDriverWait(self.driver, 8).until(
                EC.element_to_be_clickable((By.ID, "aOpcionUsuario2"))
            )
            try:
                boton_nombre.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", boton_nombre)
            time.sleep(2)

            boton_ficha = WebDriverWait(self.driver, 8).until(
                EC.presence_of_element_located((By.CLASS_NAME, "btnFichaRuc"))
            )
            try:
                boton_ficha.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", boton_ficha)
            time.sleep(6)

            iframe_el = WebDriverWait(self.driver, 8).until(
                EC.presence_of_element_located((By.ID, "iframeApplication"))
            )
            self.driver.switch_to.frame(iframe_el)
            try:
                texto_iframe = self.driver.find_element(By.TAG_NAME, "body").text
            finally:
                self.driver.switch_to.default_content()

            # Extraccion por texto en vez de un regex de una sola linea --
            # SUNAT arma esto en una tabla (etiqueta y valor en <td>
            # separados), y no hay certeza de que Selenium los una en la
            # misma linea de .text. Se busca la etiqueta y se toma la
            # primera linea no vacia despues de ella (quitando el ":" que
            # la separa del valor).
            estado = None
            idx = texto_iframe.upper().find("ESTADO DEL CONTRIBUYENTE")
            if idx != -1:
                resto = texto_iframe[idx + len("ESTADO DEL CONTRIBUYENTE"):].lstrip()
                if resto.startswith(":"):
                    resto = resto[1:]
                for linea in resto.splitlines():
                    linea = linea.strip()
                    if linea:
                        estado = linea[:50]
                        break

            # Cierra el desplegable del nombre (clic afuera) para no dejar
            # nada tapando los enlaces que busca _navegar_a_buzon_notificaciones
            # despues -- best effort, esa funcion ya es tolerante a esto.
            try:
                self.driver.find_element(By.TAG_NAME, "body").click()
            except Exception:
                pass

            if estado:
                logger.info(f"Estado del contribuyente detectado en la sesion de SUNAT: '{estado}'")
            else:
                logger.warning("Se abrio la Ficha RUC pero no se encontro el texto 'Estado del Contribuyente'")
            return estado
        except Exception as e:
            logger.warning(f"No se pudo detectar el estado del contribuyente desde la Ficha RUC (no es grave): {str(e)}")
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            return None

    def _click_condicional(self):
        """
        Maneja diferentes flujos de navegación después del login, dependiendo de lo que muestre la interfaz.
        
        Returns:
            bool: True si el proceso fue exitoso, False en caso contrario
        """
        try:
            time.sleep(5)
            logger.info("Iniciando proceso de detección de flujos")

            def click_boton_siguiente():
                """
                Función interna para hacer click en el botón "siguiente" de un
                wizard/carrusel que SUNAT solía mostrar tras el login. SUNAT ya
                no siempre muestra este paso (verificado: en una sesión normal
                de Menú SOL ese botón ya no existe en la página), así que esto
                se trata como opcional: si no aparece en unos segundos, se
                asume que no hace falta y se continúa con la navegación.
                """
                try:
                    logger.info("Intentando click en botón siguiente...")
                    self.driver.switch_to.default_content()
                    time.sleep(3)

                    xpath_boton = "/html/body/div[3]/div[2]/div/ul[2]/li[5]/a"
                    espera_corta = WebDriverWait(self.driver, 5)
                    try:
                        boton_siguiente = espera_corta.until(
                            EC.element_to_be_clickable((By.XPATH, xpath_boton))
                        )
                    except TimeoutException:
                        logger.info("No se encontró el botón siguiente (SUNAT ya no lo muestra en esta sesión); "
                                    "se continúa sin hacer clic.")
                        return True

                    try:
                        logger.info("Intentando click normal...")
                        boton_siguiente.click()
                    except Exception:
                        try:
                            logger.info("Intentando click con JavaScript...")
                            self.driver.execute_script("arguments[0].click();", boton_siguiente)
                        except Exception as e:
                            logger.warning(f"No se pudo hacer click en botón siguiente, se continúa igual: {str(e)}")
                            return True

                    logger.info("Click exitoso en botón siguiente")
                    return True

                except Exception as e:
                    logger.warning(f"Error inesperado al buscar/clickear botón siguiente, se continúa igual: {str(e)}")
                    return True

            # Asegurarnos de estar en la ventana correcta (Menú SOL)
            ventanas = self.driver.window_handles
            ventana_encontrada = False
            for ventana in ventanas:
                self.driver.switch_to.window(ventana)
                self._ocultar_ventana_si_corresponde()
                if "SUNAT - Menú SOL" in self.driver.title:
                    logger.info("Encontrada ventana de Menú SOL")
                    ventana_encontrada = True
                    break
            
            if not ventana_encontrada:
                logger.error("No se encontró la ventana de Menú SOL")
                return False

            def buscar_y_procesar_flujos():
                """Función interna para buscar y procesar flujos"""
                try:
                    self.driver.switch_to.default_content()
                    logger.info("Buscando iframes en la página...")
                    time.sleep(2)
                    
                    iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                    logger.info(f"Se encontraron {len(iframes)} iframes")
                    
                    for index, iframe in enumerate(iframes):
                        try:
                            logger.info(f"Analizando iframe {index + 1}")
                            
                            if not iframe.is_displayed():
                                logger.info(f"Iframe {index + 1} no está visible, continuando...")
                                continue
                            
                            self.driver.switch_to.frame(iframe)
                            logger.info(f"Cambiado exitosamente al iframe {index + 1}")
                            time.sleep(1)
                            
                            logger.info("Buscando elementos del Flujo 1...")
                            finalizar_buttons = self.driver.find_elements(By.ID, "btnFinalizarValidacionDatos")
                            if finalizar_buttons and any(btn.is_displayed() for btn in finalizar_buttons):
                                logger.info("¡ENCONTRADO FLUJO 1!")
                                return "flujo1", index
                            
                            logger.info("Buscando elementos del Flujo 2...")
                            buzon_buttons = self.driver.find_elements(By.ID, "btnBuzon")
                            if buzon_buttons and any(btn.is_displayed() for btn in buzon_buttons):
                                logger.info("¡ENCONTRADO FLUJO 2!")
                                return "flujo2", index
                            
                            self.driver.switch_to.default_content()
                            
                        except Exception as e:
                            logger.error(f"Error al analizar iframe {index + 1}: {str(e)}")
                            self.driver.switch_to.default_content()
                            continue
                    
                    logger.info("No se encontraron flujos en los iframes")
                    return None, None
                    
                except Exception as e:
                    logger.error(f"Error en buscar_y_procesar_flujos: {str(e)}")
                    self.driver.switch_to.default_content()
                    return None, None

            # Buscar y procesar los flujos
            flujo_detectado, iframe_index = buscar_y_procesar_flujos()
            # Fase 3: se guarda tal cual se detecto (o "sin_flujo" si no se
            # encontro ninguno) para el chequeo canario -- puramente
            # informativo, no cambia nada del control de flujo de abajo.
            self.flujo_detectado = flujo_detectado or "sin_flujo"

            if flujo_detectado == "flujo1":
                try:
                    logger.info("Procesando Flujo 1...")
                    self.driver.switch_to.default_content()
                    time.sleep(2)
                    iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                    self.driver.switch_to.frame(iframes[iframe_index])
                    logger.info("Volviendo al iframe del Flujo 1")
                    time.sleep(2)
                    
                    wait = WebDriverWait(self.driver, config.TIEMPO_ESPERA_DEFAULT)
                    
                    # Click en Finalizar
                    max_intentos = 3
                    for intento in range(max_intentos):
                        try:
                            logger.info(f"Intento {intento + 1} de click en Finalizar")
                            finalizar_button = wait.until(
                                EC.element_to_be_clickable((By.ID, "btnFinalizarValidacionDatos"))
                            )
                            finalizar_button.click()
                            logger.info("Click exitoso en botón Finalizar")
                            break
                        except Exception as e:
                            if intento == max_intentos - 1:
                                raise e
                            logger.warning(f"Reintentando click en Finalizar... ({str(e)})")
                            time.sleep(2)
                    
                    time.sleep(3)
                    
                    # Click en Continuar
                    self.driver.switch_to.default_content()
                    self.driver.switch_to.frame(iframes[iframe_index])
                    time.sleep(2)
                    
                    for intento in range(max_intentos):
                        try:
                            logger.info(f"Intento {intento + 1} de click en Continuar")
                            continuar_button = wait.until(
                                EC.element_to_be_clickable((By.ID, "btnCerrar"))
                            )
                            continuar_button.click()
                            logger.info("Click exitoso en Continuar")
                            break
                        except Exception as e:
                            if intento == max_intentos - 1:
                                raise e
                            logger.warning(f"Reintentando click en Continuar... ({str(e)})")
                            time.sleep(2)
                    
                    # Click en botón siguiente después de procesar Flujo 1
                    time.sleep(3)
                    if not click_boton_siguiente():
                        logger.error("Error al hacer click en botón siguiente después de Flujo 1")
                        return False
                    
                    return True
                    
                except Exception as e:
                    logger.error(f"Error procesando Flujo 1: {str(e)}")
                    return False
                    
            elif flujo_detectado == "flujo2":
                try:
                    logger.info("Procesando Flujo 2...")
                    self.driver.switch_to.default_content()
                    time.sleep(2)
                    iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                    self.driver.switch_to.frame(iframes[iframe_index])
                    logger.info("Volviendo al iframe del Flujo 2")
                    time.sleep(2)
                    
                    wait = WebDriverWait(self.driver, config.TIEMPO_ESPERA_DEFAULT)
                    
                    # Click en Buzón
                    max_intentos = 3
                    for intento in range(max_intentos):
                        try:
                            logger.info(f"Intento {intento + 1} de click en Buzón")
                            buzon_button = wait.until(
                                EC.element_to_be_clickable((By.ID, "btnBuzon"))
                            )
                            try:
                                buzon_button.click()
                            except:
                                self.driver.execute_script("arguments[0].click();", buzon_button)
                            logger.info("Click exitoso en Buzón Electrónico")
                            break
                        except Exception as e:
                            if intento == max_intentos - 1:
                                raise e
                            logger.warning(f"Reintentando click en Buzón... ({str(e)})")
                            time.sleep(2)
                    
                    time.sleep(3)
                    
                    # Click en botón siguiente después de procesar Flujo 2
                    if not click_boton_siguiente():
                        logger.error("Error al hacer click en botón siguiente después de Flujo 2")
                        return False
                    
                    return True
                    
                except Exception as e:
                    logger.error(f"Error procesando Flujo 2: {str(e)}")
                    return False
            
            else:
                logger.info("No se detectó ningún flujo, procediendo directamente al botón siguiente")
                if not click_boton_siguiente():
                    logger.error("Error al hacer click en botón siguiente en caso sin flujos")
                    return False
                return True

        except Exception as e:
            logger.error(f"Error general en click_condicional: {str(e)}")
            self.driver.switch_to.default_content()
            return False
    
    def _navegar_a_buzon_notificaciones(self):
        """
        Navega al Buzón de Notificaciones en el portal SUNAT.
        
        Returns:
            bool: True si la navegación fue exitosa, False en caso contrario
        """
        try:
            logger.info("Navegando al Buzón de Notificaciones")
            
            # Dar más tiempo para que la página cargue completamente
            time.sleep(5)
            
            # Imprimir título de la página para diagnóstico
            logger.info(f"Título de la página: {self.driver.title}")
            
            # Asegurarse de estar en el contexto principal (fuera de cualquier iframe)
            self.driver.switch_to.default_content()
            
            # Buscar todos los iframes y verificar cada uno
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            logger.info(f"Número de iframes encontrados: {len(iframes)}")
            
            # Intentar varias estrategias para encontrar el Buzón Notificaciones
            
            # Estrategia 1: Buscar directamente sin cambiar a iframe
            try:
                logger.info("Estrategia 1: Buscando Buzón Notificaciones en la página principal...")
                xpath_buzon = "/html/body/div[2]/div/div[1]/div/div/div/div[1]/div[2]/div/div[1]/a[1]"
                wait = WebDriverWait(self.driver, 5)
                buzon_elemento = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_buzon)))
                buzon_elemento.click()
                logger.info("Clic exitoso usando Estrategia 1")
                time.sleep(3)
                return True
            except Exception as e:
                logger.warning(f"Estrategia 1 falló: {str(e)}")
            
            # Estrategia 2: Buscar por texto en vez de XPath
            try:
                logger.info("Estrategia 2: Buscando por texto 'Buzón Notificaciones'...")
                buzon_elemento = self.driver.find_element(By.XPATH, "//a[contains(text(), 'Buzón Notificaciones')]")
                self.driver.execute_script("arguments[0].click();", buzon_elemento)
                logger.info("Clic exitoso usando Estrategia 2")
                time.sleep(3)
                return True
            except Exception as e:
                logger.warning(f"Estrategia 2 falló: {str(e)}")
            
            # Estrategia 3: Buscar en todos los iframes
            for i, iframe in enumerate(iframes):
                try:
                    logger.info(f"Estrategia 3: Cambiando al iframe {i+1}...")
                    self.driver.switch_to.frame(iframe)
                    
                    try:
                        buzon_elemento = self.driver.find_element(By.XPATH, "//a[contains(text(), 'Buzón')]")
                        self.driver.execute_script("arguments[0].click();", buzon_elemento)
                        logger.info(f"Clic exitoso en Buzón desde iframe {i+1}")
                        time.sleep(3)
                        return True
                    except:
                        logger.info(f"No se encontró 'Buzón' en iframe {i+1}")
                    
                    # Volver al contenido principal para probar el siguiente iframe
                    self.driver.switch_to.default_content()
                except Exception as e:
                    logger.error(f"Error al cambiar al iframe {i+1}: {str(e)}")
                    self.driver.switch_to.default_content()
            
            # Estrategia 4: Intentar hacer clic en cualquier enlace que pueda ser el Buzón
            try:
                logger.info("Estrategia 4: Buscando enlaces que puedan ser el Buzón...")
                enlaces = self.driver.find_elements(By.TAG_NAME, "a")
                logger.info(f"Número total de enlaces encontrados: {len(enlaces)}")
                
                for i, enlace in enumerate(enlaces[:20]):  # Revisar los primeros 20 enlaces
                    try:
                        texto = enlace.text.strip()
                        if texto and ("Buzón" in texto or "Notificaciones" in texto):
                            logger.info(f"Encontrado posible enlace de Buzón: '{texto}'")
                            self.driver.execute_script("arguments[0].click();", enlace)
                            logger.info(f"Clic exitoso en '{texto}'")
                            time.sleep(3)
                            return True
                    except:
                        continue
                
                logger.warning("No se encontró ningún enlace que parezca ser el Buzón")
            except Exception as e:
                logger.error(f"Estrategia 4 falló: {str(e)}")
            
            # Si llegamos aquí, todas las estrategias fallaron
            logger.error("Todas las estrategias fallaron para encontrar el Buzón Notificaciones")
            
            # Capturar una imagen para diagnóstico
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join(config.LOGS_DIR, f"error_buzon_{timestamp}.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Se guardó una captura de pantalla en: {screenshot_path}")
            
            return False
            
        except Exception as e:
            logger.error(f"Error al navegar al Buzón de Notificaciones: {str(e)}")
            # Capturar una imagen para diagnóstico
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join(config.LOGS_DIR, f"error_buzon_exc_{timestamp}.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Se guardó una captura de pantalla en: {screenshot_path}")
            return False
    
    def _esperar_descarga(self, timeout=60):  # Aumentado de 30 a 60 segundos
        """
        Espera a que se complete la descarga del archivo PDF
        
        Args:
            timeout (int): Tiempo máximo de espera en segundos
                
        Returns:
            bool: True si la descarga se completó, False en caso contrario
        """
        try:
            logger.info("=== Esperando que se complete la descarga ===")
            tiempo_inicio = datetime.now()
            ultimo_pdf = None
            archivos_iniciales = set(os.listdir(self.download_dir))
            
            while (datetime.now() - tiempo_inicio).seconds < timeout:
                # Buscar archivos nuevos en la carpeta de descargas
                archivos_actuales = set(os.listdir(self.download_dir))
                archivos_nuevos = archivos_actuales - archivos_iniciales
                
                # Si hay archivos .crdownload, la descarga está en progreso
                if any(f.endswith('.crdownload') for f in archivos_actuales):
                    logger.info("Descarga en progreso (archivos .crdownload encontrados)...")
                    time.sleep(1)
                    continue
                
                # Si hay archivos .tmp nuevos, verificar si han terminado de crecer
                tmp_files = [f for f in archivos_nuevos if f.endswith('.tmp')]
                if tmp_files:
                    for tmp_file in tmp_files:
                        ruta_tmp = os.path.join(self.download_dir, tmp_file)
                        tamaño_actual = os.path.getsize(ruta_tmp)
                        logger.info(f"Verificando archivo temporal: {tmp_file} ({tamaño_actual} bytes)")
                        time.sleep(3)  # Esperar un momento
                        
                        # Verificar si el tamaño cambió (sigue descargando)
                        if os.path.exists(ruta_tmp):  # Asegurarse de que el archivo sigue existiendo
                            tamaño_nuevo = os.path.getsize(ruta_tmp)
                            if tamaño_nuevo > tamaño_actual:
                                logger.info(f"El archivo todavía está creciendo: {tamaño_actual} -> {tamaño_nuevo} bytes")
                                continue  # Seguir esperando
                        
                    # Si llegamos aquí, los archivos tmp no han crecido por 3 segundos
                    logger.info("Archivos temporales estabilizados, considerando la descarga como completa")
                    return True
                
                # Si hay archivos .pdf y no hay .crdownload, la descarga está completa
                pdf_files = [f for f in archivos_nuevos if f.endswith('.pdf')]
                if pdf_files:
                    logger.info("¡Descarga completada! (encontrados archivos PDF)")
                    # Obtener el nombre del último archivo descargado
                    ultimo_pdf = max([os.path.join(self.download_dir, f) for f in pdf_files], 
                                   key=os.path.getctime)
                    logger.info(f"Archivo descargado: {os.path.basename(ultimo_pdf)}")
                    return True
                    
                # Si no hay nuevos archivos pero tampoco hay descargas en progreso,
                # esperar un poco más por si el archivo tarda en aparecer
                if not archivos_nuevos:
                    logger.info("Esperando que aparezcan archivos nuevos...")
                    time.sleep(1)
                    continue
                
                # Si hay archivos nuevos que no son PDF ni temporales reconocidos,
                # verificar si son lo suficientemente grandes para ser un PDF
                other_files = [f for f in archivos_nuevos 
                             if not f.endswith('.pdf') and not f.endswith('.crdownload') and not f.endswith('.tmp')]
                
                if other_files:
                    for other_file in other_files:
                        ruta_file = os.path.join(self.download_dir, other_file)
                        tamaño = os.path.getsize(ruta_file)
                        logger.info(f"Archivo nuevo no reconocido: {other_file} ({tamaño} bytes)")
                        
                        # Si el archivo es grande, considerarlo como una descarga completa
                        if tamaño > 10000:  # Más de 10KB
                            logger.info(f"Archivo considerado como descarga completa por tamaño")
                            return True
                
                # Pequeña pausa para no consumir demasiada CPU
                time.sleep(1)
                    
            logger.warning(f"Tiempo de espera agotado después de {timeout} segundos")
            # Aunque se agotó el tiempo, considerarlo exitoso si hay algún archivo nuevo
            if archivos_actuales - archivos_iniciales:
                logger.info("Considerando descarga como exitosa aunque se agotó el tiempo (hay archivos nuevos)")
                return True
                
            return False
                
        except Exception as e:
            logger.error(f"Error al esperar la descarga: {str(e)}")
            return False
            
    def _descargar_pdf_mensaje(self):
        """
        Descarga el PDF asociado al mensaje actual
        
        Returns:
            bool: True si la descarga fue exitosa, False en caso contrario
        """
        try:
            logger.info("=== Iniciando proceso de descarga de PDF ===")
            
            # Esperar y cambiar al iframe del contenedor de mensajes
            wait = WebDriverWait(self.driver, 15)
            iframe = wait.until(
                EC.presence_of_element_located((By.ID, "contenedorMensaje"))
            )
            
            logger.info("Contenedor de mensaje encontrado")
            self.driver.switch_to.frame("contenedorMensaje")
            time.sleep(2)
            
            try:
                # Obtener los parámetros de la URL del iframe
                iframe_src = iframe.get_attribute('src')
                logger.info(f"URL del iframe: {iframe_src}")
                
                # Buscar elementos que contengan el enlace de descarga
                elementos_clickeables = self.driver.find_elements(By.TAG_NAME, "a")
                
                descarga_iniciada = False
                for elemento in elementos_clickeables:
                    href = elemento.get_attribute('href')
                    onclick = elemento.get_attribute('onclick')
                    
                    if href and 'goArchivoDescarga' in href:
                        logger.info("Encontrado enlace de descarga por href")
                        elemento.click()
                        descarga_iniciada = True
                        break
                    elif onclick and 'goArchivoDescarga' in onclick:
                        logger.info("Encontrado enlace de descarga por onclick")
                        elemento.click()
                        descarga_iniciada = True
                        break
                
                # Si no se encuentra el enlace, intentar ejecutar el JavaScript directamente
                if not descarga_iniciada:
                    logger.info("Intentando ejecutar JavaScript de descarga directamente")
                    try:
                        # Extraer los parámetros de la URL del iframe
                        params = iframe_src.split('datos=')[1]
                        params_dict = eval(params)
                        id_archivo = params_dict.get('id_archivo')
                        cod_mensaje = params_dict.get('cod_mensaje')
                        
                        if id_archivo and cod_mensaje:
                            script = f"goArchivoDescarga({id_archivo},0,{cod_mensaje})"
                            self.driver.execute_script(script)
                            logger.info(f"Ejecutado script de descarga: {script}")
                            descarga_iniciada = True
                    except Exception as e:
                        logger.error(f"Error al ejecutar JavaScript de descarga: {str(e)}")
                
                if descarga_iniciada:
                    logger.info("Proceso de descarga iniciado")
                    # Esperar a que se complete la descarga
                    if self._esperar_descarga():
                        logger.info("Descarga completada exitosamente")
                    else:
                        logger.error("Error: La descarga no se completó en el tiempo esperado")
                
                # Volver al contenido principal
                self.driver.switch_to.default_content()
                return descarga_iniciada
                
            except Exception as e:
                logger.error(f"Error al intentar descargar el PDF: {str(e)}")
                self.driver.switch_to.default_content()
                return False
                
        except Exception as e:
            logger.error(f"Error al acceder al contenedor de mensajes: {str(e)}")
            self.driver.switch_to.default_content()
            return False
            
    def _descargar_documento_constancia(self):
        """
        Descarga el documento de constancia desde el mensaje actual
        
        Returns:
            bool: True si la descarga fue exitosa, False en caso contrario
        """
        try:
            logger.info("=== Descargando documento constancia ===")
            
            # Esperar a que el iframe se cargue
            wait = WebDriverWait(self.driver, 15)
            
            # Usar el XPath para el iframe
            iframe_xpath = "/html/body/div[2]/div/div[2]/div[2]/div/div/div[5]/div/iframe"
            
            try:
                iframe = wait.until(
                    EC.presence_of_element_located((By.XPATH, iframe_xpath))
                )
                logger.info("iframe encontrado por XPath")
            except:
                try:
                    iframe = wait.until(
                        EC.presence_of_element_located((By.ID, "contenedorMensaje"))
                    )
                    logger.info("iframe encontrado por ID")
                except Exception as e:
                    logger.error(f"No se pudo encontrar el iframe: {str(e)}")
                    return False
            
            # Cambiar al iframe
            logger.info("Cambiando al iframe contenedorMensaje...")
            self.driver.switch_to.frame(iframe)
            
            # Buscar CUALQUIER enlace dentro del iframe
            logger.info("Buscando enlaces dentro del iframe...")
            enlaces = self.driver.find_elements(By.TAG_NAME, "a")
            
            # Imprimir todos los enlaces para depuración
            for i, enlace in enumerate(enlaces):
                href = enlace.get_attribute('href')
                texto = enlace.text
                logger.info(f"Enlace {i+1}: Texto='{texto}', href='{href}'")
                
                # Si encontramos un enlace con javascript:goArchivoDescarga, extraer los parámetros
                if href and 'goArchivoDescarga' in href:
                    logger.info(f"Encontrado enlace con goArchivoDescarga: {href}")
                    
                    # Extraer los parámetros: goArchivoDescarga(id_archivo, algo, cod_mensaje)
                    try:
                        params = href.split('goArchivoDescarga(')[1].split(')')[0].split(',')
                        id_archivo = params[0].strip()
                        cod_mensaje = params[2].strip()
                        
                        # Ejecutar directamente el JavaScript
                        logger.info(f"Ejecutando: goArchivoDescarga({id_archivo},0,{cod_mensaje})")
                        self.driver.execute_script(f"goArchivoDescarga({id_archivo},0,{cod_mensaje})")
                        
                        # Esperar a que se complete la descarga
                        if self._esperar_descarga(timeout=30):
                            logger.info("Documento descargado exitosamente")
                            # Agregar logs detallados para diagnóstico de archivos descargados
                            logger.info(f"Documento descargado en carpeta: {self.download_dir}")
                            logger.info(f"Listado de archivos en carpeta de descarga:")
                            try:
                                for archivo in os.listdir(self.download_dir):
                                    ruta_completa = os.path.join(self.download_dir, archivo)
                                    tamaño = os.path.getsize(ruta_completa) if os.path.isfile(ruta_completa) else "Es una carpeta"
                                    fecha_mod = datetime.fromtimestamp(os.path.getmtime(ruta_completa)).strftime("%Y-%m-%d %H:%M:%S")
                                    logger.info(f"  - {archivo} (tamaño: {tamaño} bytes, modificado: {fecha_mod})")
                            except Exception as e:
                                logger.error(f"Error al listar archivos: {str(e)}")
                            self.driver.switch_to.default_content()
                            return True
                        else:
                            logger.error("La descarga no se completó en el tiempo esperado")
                    except Exception as e:
                        logger.error(f"Error al ejecutar goArchivoDescarga: {str(e)}")
            
            # Si no encontramos ningún enlace con goArchivoDescarga, buscar constancia_
            logger.info("Buscando enlaces con constancia_...")
            for enlace in enlaces:
                texto = enlace.text
                if 'constancia_' in texto:
                    logger.info(f"Encontrado enlace con constancia_: {texto}")
                    try:
                        enlace.click()
                        if self._esperar_descarga(timeout=30):
                            logger.info("Documento descargado exitosamente")
                            self.driver.switch_to.default_content()
                            return True
                    except Exception as e:
                        logger.error(f"Error al hacer clic en enlace constancia_: {str(e)}")
            
            # Si llegamos aquí, no se pudo descargar
            logger.error("No se pudo encontrar o ejecutar el enlace de descarga")
            self.driver.switch_to.default_content()
            return False
            
        except Exception as e:
            logger.error(f"Error al descargar documento constancia: {str(e)}")
            try:
                self.driver.switch_to.default_content()
            except:
                pass
            return False
    def _recargar_elementos_mensaje(self, mensajes, indice_actual):
        """
        Recarga los elementos de los mensajes después de navegar de regreso a la lista
        
        Args:
            mensajes (list): Lista de mensajes a actualizar
            indice_actual (int): Índice del mensaje actual (-1 para actualizar todos)
        
        Returns:
            bool: True si se actualizaron exitosamente, False en caso contrario
        """
        try:
            logger.info(f"Recargando elementos de mensajes {'(todos)' if indice_actual == -1 else f'(desde índice {indice_actual})'}...")
            
            # Buscar todos los elementos de fecha
            elementos_fecha = self.driver.find_elements(By.CLASS_NAME, "fecPublica")
            if not elementos_fecha:
                elementos_fecha = self.driver.find_elements(By.XPATH, "//div/small[contains(@class, 'text-muted')]")
            
            if not elementos_fecha:
                logger.error("No se encontraron elementos de fecha para recargar.")
                return False
            
            logger.info(f"Se encontraron {len(elementos_fecha)} elementos de fecha para recargar.")
            
            # Determinar qué índices actualizar
            indices_a_actualizar = range(len(mensajes)) if indice_actual == -1 else range(indice_actual, len(mensajes))
            
            for i in indices_a_actualizar:
                if mensajes[i]['procesado']:
                    logger.info(f"Mensaje {i+1} ya procesado, no es necesario recargar.")
                    continue
                    
                logger.info(f"Recargando mensaje {i+1}...")
                
                # Intentar encontrar el mensaje correspondiente con varios métodos
                mensaje_encontrado = False
                
                # Método 1: Por índice original (más rápido pero menos confiable)
                if not mensaje_encontrado and mensajes[i]['indice'] < len(elementos_fecha):
                    try:
                        indice_original = mensajes[i]['indice']
                        elem_fecha = elementos_fecha[indice_original]
                        li_padre = elem_fecha.find_element(By.XPATH, "./ancestor::li")
                        mensaje = li_padre.find_element(By.TAG_NAME, "a")
                        mensajes[i]['elemento'] = mensaje
                        mensaje_encontrado = True
                        logger.info(f"Mensaje {i+1} recargado por índice original.")
                    except:
                        logger.warning(f"No se pudo recargar el mensaje {i+1} por índice original.")
                
                # Método 2: Buscar por asunto, si está disponible
                if not mensaje_encontrado and mensajes[i]['asunto']:
                    try:
                        xpath_asunto = f"//strong[contains(text(), '{mensajes[i]['asunto']}')]/ancestor::li//a"
                        mensajes[i]['elemento'] = self.driver.find_element(By.XPATH, xpath_asunto)
                        mensaje_encontrado = True
                        logger.info(f"Mensaje {i+1} recargado por asunto.")
                    except:
                        logger.warning(f"No se pudo recargar el mensaje {i+1} por asunto.")
                
                # Método 3: Buscar por fecha y hora exactas
                if not mensaje_encontrado:
                    fecha_hora_buscar = mensajes[i]['texto_hora']
                    for j, elem_fecha in enumerate(elementos_fecha):
                        try:
                            texto_fecha = elem_fecha.text.strip()
                            if texto_fecha == fecha_hora_buscar:
                                li_padre = elem_fecha.find_element(By.XPATH, "./ancestor::li")
                                mensaje = li_padre.find_element(By.TAG_NAME, "a")
                                mensajes[i]['elemento'] = mensaje
                                mensaje_encontrado = True
                                logger.info(f"Mensaje {i+1} recargado por coincidencia de fecha/hora exacta.")
                                break
                        except:
                            continue
                
                # Método 4: Buscar mensajes no procesados con la misma fecha (sin hora)
                if not mensaje_encontrado:
                    fecha_buscar = mensajes[i]['fecha']
                    for j, elem_fecha in enumerate(elementos_fecha):
                        try:
                            texto_fecha = elem_fecha.text.strip()
                            partes_fecha = texto_fecha.split()
                            if partes_fecha and partes_fecha[0] == fecha_buscar:
                                # Verificar que este mensaje no haya sido asignado a otro índice ya procesado
                                ya_asignado = False
                                for k in range(i):
                                    if mensajes[k]['procesado'] and \
                                       mensajes[k].get('nuevo_indice') == j:
                                        ya_asignado = True
                                        break
                                
                                if not ya_asignado:
                                    li_padre = elem_fecha.find_element(By.XPATH, "./ancestor::li")
                                    mensaje = li_padre.find_element(By.TAG_NAME, "a")
                                    mensajes[i]['elemento'] = mensaje
                                    mensajes[i]['nuevo_indice'] = j
                                    mensaje_encontrado = True
                                    logger.info(f"Mensaje {i+1} recargado por coincidencia de fecha (sin hora). Usado índice {j}.")
                                    break
                        except:
                            continue
                
                if not mensaje_encontrado:
                    logger.warning(f"¡ADVERTENCIA! No se pudo recargar el mensaje {i+1} por ningún método.")
            
            return True
            
        except Exception as e:
            logger.error(f"Error al recargar elementos de mensaje: {str(e)}")
            return False
    
    def _procesar_mensajes_del_dia(self, max_intentos=None):
        """
        Procesa todos los mensajes del día actual en orden (del más antiguo al más reciente)
        Descarga el documento de constancia para cada mensaje, manejando casos donde hay mensajes
        con la misma fecha y hora.
        
        Args:
            max_intentos (int, optional): Número máximo de intentos para cada mensaje
            
        Returns:
            tuple: (resultado, mensaje) donde:
                - resultado (bool): True si la operación fue exitosa, False en caso contrario
                - mensaje (str): Descripción del resultado o error
        """
        if max_intentos is None:
            max_intentos = config.MAX_INTENTOS
            
        try:
            logger.info("=== Iniciando procesamiento de mensajes del día actual ===")
            
            # Obtener la fecha actual para comparar
            fecha_actual = datetime.now().strftime("%d/%m/%Y")
            logger.info(f"Fecha actual: {fecha_actual}")
            
            # Para pruebas, se puede usar una fecha específica
            #fecha_actual = "11/03/2025"
            #logger.info(f"Fecha actual: {fecha_actual}")
            
            # Buscar todos los mensajes y sus fechas
            elementos_fecha = self.driver.find_elements(By.CLASS_NAME, "fecPublica")
            
            if not elementos_fecha:
                logger.warning("No se encontraron fechas de mensajes. Intentando buscar por XPath...")
                elementos_fecha = self.driver.find_elements(By.XPATH, "//div/small[contains(@class, 'text-muted')]")
            
            if not elementos_fecha:
                logger.info("No se pudieron encontrar fechas de mensajes.")
                return True, "No hay mensajes disponibles para procesar"
                
            logger.info(f"Se encontraron {len(elementos_fecha)} elementos de fecha.")
            
            # Recorrer los elementos de fecha y encontrar los del día actual
            mensajes_hoy = []
            
            for i, elem_fecha in enumerate(elementos_fecha):
                texto_fecha = elem_fecha.text.strip()
                logger.info(f"Fecha del mensaje {i+1}: {texto_fecha}")
                
                # Extraer solo la parte de la fecha (sin la hora)
                partes_fecha = texto_fecha.split()
                if partes_fecha:
                    fecha_mensaje = partes_fecha[0]
                    hora_mensaje = partes_fecha[1] if len(partes_fecha) > 1 else ""
                    
                    if fecha_mensaje == fecha_actual:
                        logger.info(f"¡Mensaje del día actual encontrado! Fecha: {fecha_mensaje}, Hora: {hora_mensaje}")
                        
                        # Buscar el elemento padre completo (que contiene toda la info del mensaje)
                        try:
                            # Obtener el li que contiene el mensaje completo
                            li_padre = elem_fecha.find_element(By.XPATH, "./ancestor::li")
                            
                            # Intentar obtener el asunto o título del mensaje si está disponible
                            asunto = ""
                            try:
                                # Buscar elementos con el asunto (ajustar según la estructura real de la página)
                                posibles_asuntos = li_padre.find_elements(By.TAG_NAME, "strong")
                                if posibles_asuntos:
                                    asunto = posibles_asuntos[0].text.strip()
                                else:
                                    # Intentar encontrar por otros selectores si no hay strong
                                    posibles_asuntos = li_padre.find_elements(By.CLASS_NAME, "asunto")
                                    if posibles_asuntos:
                                        asunto = posibles_asuntos[0].text.strip()
                            except:
                                # Si no se puede obtener el asunto, usar un identificador alternativo
                                try:
                                    asunto = f"Mensaje-{i+1}"
                                except:
                                    asunto = f"Sin-asunto-{i+1}"
                            
                            # Encontrar el elemento clickeable (enlace <a>)
                            mensaje_padre = None
                            try:
                                mensaje_padre = li_padre.find_element(By.TAG_NAME, "a")
                            except:
                                try:
                                    mensaje_padre = elem_fecha.find_element(By.XPATH, "./ancestor::a")
                                except:
                                    logger.error(f"No se pudo encontrar el elemento clickeable para el mensaje {i+1}")
                                    continue
                            
                            # Almacenar información adicional del mensaje para identificación posterior
                            html_id = li_padre.get_attribute('id') or ""
                            class_name = li_padre.get_attribute('class') or ""
                            
                            if mensaje_padre:
                                # Almacenar el mensaje con toda la información disponible para identificarlo
                                mensajes_hoy.append({
                                    'fecha': fecha_mensaje,
                                    'hora': hora_mensaje,
                                    'elemento': mensaje_padre,
                                    'texto_hora': texto_fecha,
                                    'asunto': asunto,
                                    'html_id': html_id,
                                    'class_name': class_name,
                                    'indice': i,
                                    'procesado': False  # Marcador para rastrear si este mensaje ya fue procesado
                                })
                        except Exception as e:
                            logger.error(f"Error al obtener detalles del mensaje {i+1}: {str(e)}")
                            continue
            
            # Si no hay mensajes del día actual, detener la ejecución
            if not mensajes_hoy:
                logger.info("No hay mensajes del día actual. Deteniendo la ejecución.")
                # Importante: devolver True en lugar de False, ya que no es un error técnico
                return True, "No hay mensajes del día actual"
            
            # Ordenar los mensajes por hora (de más antiguo a más reciente)
            mensajes_hoy.sort(key=lambda x: x['texto_hora'])
            
            # Imprimir los mensajes encontrados
            logger.info(f"Se encontraron {len(mensajes_hoy)} mensajes del día actual:")
            for i, msg in enumerate(mensajes_hoy):
                logger.info(f"  {i+1}. Hora: {msg['hora']}, Asunto: {msg['asunto']}")
            
            # Procesar cada mensaje en orden
            mensajes_procesados = 0
            
            for i, mensaje_info in enumerate(mensajes_hoy):
                if mensaje_info['procesado']:
                    logger.info(f"Mensaje {i+1} ya procesado, saltando...")
                    continue
                    
                logger.info(f"=== Procesando mensaje {i+1} de {len(mensajes_hoy)} (Hora: {mensaje_info['hora']}, Asunto: {mensaje_info['asunto']}) ===")
                
                for intento in range(max_intentos):
                    try:
                        # Hacer clic en el mensaje
                        try:
                            logger.info(f"Haciendo clic en mensaje... (intento {intento+1})")
                            mensaje_info['elemento'].click()
                        except Exception as e:
                            logger.warning(f"Error en clic normal: {str(e)}")
                            logger.info("Intentando clic con JavaScript...")
                            self.driver.execute_script("arguments[0].click();", mensaje_info['elemento'])
                        
                        logger.info("Clic exitoso en el mensaje")
                        time.sleep(3)
                        
                        # Descargar el documento constancia
                        if self._descargar_documento_constancia():
                            logger.info(f"Documento para el mensaje {i+1} descargado exitosamente")
                            mensaje_info['procesado'] = True
                            mensajes_procesados += 1
                            break  # Salir del bucle de intentos si la descarga fue exitosa
                        else:
                            logger.warning(f"Error al descargar el documento para el mensaje {i+1} - Intento {intento+1}")
                            if intento == max_intentos-1:  # Si es el último intento
                                logger.error(f"No se pudo descargar el documento para el mensaje {i+1} después de {max_intentos} intentos")
                    
                    except Exception as e:
                        logger.error(f"Error al procesar el mensaje {i+1}: {str(e)}")
                        if intento == max_intentos-1:  # Si es el último intento
                            logger.error(f"No se pudo procesar el mensaje {i+1} después de {max_intentos} intentos")
                    
                    # Si no es el último intento, volver a la lista de mensajes para reintentar
                    if intento < max_intentos-1:
                        try:
                            logger.info("Volviendo a la lista de mensajes para reintentar...")
                            self.driver.back()
                            time.sleep(3)
                            
                            # Recargar todos los elementos de la página
                            if not self._recargar_elementos_mensaje(mensajes_hoy, i):
                                logger.error("No se pudieron recargar los elementos de los mensajes")
                        except Exception as e:
                            logger.error(f"Error al volver a la lista de mensajes: {str(e)}")
                
                # Si no es el último mensaje, volver a la lista de mensajes para procesar el siguiente
                if i < len(mensajes_hoy)-1 and mensaje_info['procesado']:
                    try:
                        logger.info("Volviendo a la lista de mensajes para procesar el siguiente mensaje...")
                        self.driver.back()
                        time.sleep(3)
                        
                        # Recargar todos los elementos de la página
                        if not self._recargar_elementos_mensaje(mensajes_hoy, -1):  # -1 para recargar todos
                            logger.error("No se pudieron recargar los elementos de los mensajes")
                            # Intentar navegar al buzón nuevamente como última opción
                            self._navegar_a_buzon_notificaciones()
                            # Recargar mensajes después de navegar al buzón
                            self._recargar_mensajes_completo(mensajes_hoy, fecha_actual)
                    except Exception as e:
                        logger.error(f"Error al volver a la lista de mensajes: {str(e)}")
                        # Intentar navegar al buzón nuevamente como última opción
                        self._navegar_a_buzon_notificaciones()
                        # Recargar mensajes después de navegar al buzón
                        self._recargar_mensajes_completo(mensajes_hoy, fecha_actual)
            
            logger.info(f"=== Procesamiento de mensajes completado. {mensajes_procesados} de {len(mensajes_hoy)} mensajes procesados exitosamente ===")
            return True, f"Procesados {mensajes_procesados} de {len(mensajes_hoy)} mensajes"
            
        except Exception as e:
            logger.error(f"Error al procesar mensajes del día: {str(e)}")
            # Capturar una imagen para diagnóstico
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join(config.LOGS_DIR, f"error_proceso_mensajes_{timestamp}.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Se guardó una captura de pantalla en: {screenshot_path}")
            return False, f"Error al procesar mensajes: {str(e)}"    
    
    
    def _procesar_mensajes_periodo(self, dias_atras=1, max_intentos=None):
        """
        Procesa mensajes del día actual y de días anteriores (configurable), evitando
        duplicados mediante un sistema de seguimiento.
        
        Args:
            dias_atras (int): Número de días atrás a considerar (además del día actual)
            max_intentos (int, optional): Número máximo de intentos para cada mensaje
                
        Returns:
            tuple: (resultado, mensaje) donde:
                - resultado (bool): True si la operación fue exitosa, False en caso contrario
                - mensaje (str): Descripción del resultado o error
        """
        if max_intentos is None:
            max_intentos = config.MAX_INTENTOS
            
        try:
            logger.info(f"=== Iniciando procesamiento de mensajes del día actual y {dias_atras} días atrás ===")
            
            # Inicializar tracker de mensajes
            from mensaje_tracker import MensajeTracker
            tracker = MensajeTracker(config.BASE_DIR)
            
            # Obtener RUC de la empresa actual para el seguimiento
            ruc_empresa = self.empresa['ruc']
            
            # Calcular fechas a procesar
            fechas_a_procesar = []
            hoy = datetime.now()
            for i in range(dias_atras + 1):  # +1 para incluir el día actual
                fecha = (hoy - timedelta(days=i)).strftime("%d/%m/%Y")
                fechas_a_procesar.append(fecha)
            
            logger.info(f"Fechas a procesar: {fechas_a_procesar}")
            
            # Buscar todos los mensajes y sus fechas
            elementos_fecha = self.driver.find_elements(By.CLASS_NAME, "fecPublica")
            
            if not elementos_fecha:
                logger.warning("No se encontraron fechas de mensajes. Intentando buscar por XPath...")
                elementos_fecha = self.driver.find_elements(By.XPATH, "//div/small[contains(@class, 'text-muted')]")
            
            if not elementos_fecha:
                logger.info("No se pudieron encontrar fechas de mensajes.")
                return True, "No hay mensajes disponibles para procesar"
                
            logger.info(f"Se encontraron {len(elementos_fecha)} elementos de fecha.")
            
            # Recorrer los elementos de fecha y encontrar los que corresponden a las fechas a procesar
            mensajes_a_procesar = []
            
            for i, elem_fecha in enumerate(elementos_fecha):
                texto_fecha = elem_fecha.text.strip()
                logger.info(f"Fecha del mensaje {i+1}: {texto_fecha}")
                
                # Extraer solo la parte de la fecha (sin la hora)
                partes_fecha = texto_fecha.split()
                if partes_fecha:
                    fecha_mensaje = partes_fecha[0]
                    hora_mensaje = partes_fecha[1] if len(partes_fecha) > 1 else ""
                    
                    if fecha_mensaje in fechas_a_procesar:
                        logger.info(f"¡Mensaje con fecha a procesar encontrado! Fecha: {fecha_mensaje}, Hora: {hora_mensaje}")
                        
                        # Buscar el elemento padre completo (que contiene toda la info del mensaje)
                        try:
                            # Obtener el li que contiene el mensaje completo
                            li_padre = elem_fecha.find_element(By.XPATH, "./ancestor::li")
                            
                            # Intentar obtener el asunto o título del mensaje si está disponible
                            asunto = ""
                            try:
                                # Buscar elementos con el asunto
                                posibles_asuntos = li_padre.find_elements(By.TAG_NAME, "strong")
                                if posibles_asuntos:
                                    asunto = posibles_asuntos[0].text.strip()
                                else:
                                    # Intentar encontrar por otros selectores si no hay strong
                                    posibles_asuntos = li_padre.find_elements(By.CLASS_NAME, "asunto")
                                    if posibles_asuntos:
                                        asunto = posibles_asuntos[0].text.strip()
                            except:
                                # Si no se puede obtener el asunto, usar un identificador alternativo
                                try:
                                    asunto = f"Mensaje-{i+1}"
                                except:
                                    asunto = f"Sin-asunto-{i+1}"
                            
                            # Encontrar el elemento clickeable (enlace <a>)
                            mensaje_padre = None
                            try:
                                mensaje_padre = li_padre.find_element(By.TAG_NAME, "a")
                            except:
                                try:
                                    mensaje_padre = elem_fecha.find_element(By.XPATH, "./ancestor::a")
                                except:
                                    logger.error(f"No se pudo encontrar el elemento clickeable para el mensaje {i+1}")
                                    continue
                            
                            # Almacenar información adicional del mensaje para identificación posterior
                            html_id = li_padre.get_attribute('id') or ""
                            class_name = li_padre.get_attribute('class') or ""
                            
                            # Crear un identificador único para este mensaje
                            # Combinamos fecha, hora, asunto y cualquier otro dato único disponible
                            mensaje_id = f"{fecha_mensaje}_{hora_mensaje}_{asunto}_{html_id}"
                            
                            # Verificar si este mensaje ya fue procesado anteriormente
                            if tracker.es_mensaje_procesado(ruc_empresa, mensaje_id):
                                logger.info(f"El mensaje ya fue procesado anteriormente, saltando: {mensaje_id}")
                                continue
                            
                            if mensaje_padre:
                                # Almacenar el mensaje con toda la información disponible para identificarlo
                                mensajes_a_procesar.append({
                                    'fecha': fecha_mensaje,
                                    'hora': hora_mensaje,
                                    'elemento': mensaje_padre,
                                    'texto_hora': texto_fecha,
                                    'asunto': asunto,
                                    'html_id': html_id,
                                    'class_name': class_name,
                                    'indice': i,
                                    'procesado': False,  # Marcador para rastrear si este mensaje ya fue procesado
                                    'mensaje_id': mensaje_id  # Identificador único para seguimiento
                                })
                        except Exception as e:
                            logger.error(f"Error al obtener detalles del mensaje {i+1}: {str(e)}")
                            continue
            
            # Si no hay mensajes a procesar, detener la ejecución
            if not mensajes_a_procesar:
                logger.info(f"No hay mensajes para procesar en las fechas especificadas: {fechas_a_procesar}")
                # Importante: devolver True en lugar de False, ya que no es un error técnico
                return True, f"No hay mensajes para procesar en las fechas: {fechas_a_procesar}"
            
            # Ordenar los mensajes por fecha y hora (de más antiguo a más reciente)
            mensajes_a_procesar.sort(key=lambda x: f"{x['fecha']}_{x['hora']}")
            
            # Imprimir los mensajes encontrados
            logger.info(f"Se encontraron {len(mensajes_a_procesar)} mensajes a procesar:")
            for i, msg in enumerate(mensajes_a_procesar):
                logger.info(f"  {i+1}. Fecha: {msg['fecha']}, Hora: {msg['hora']}, Asunto: {msg['asunto']}")
            
            # Procesar cada mensaje en orden
            mensajes_procesados = 0
            
            for i, mensaje_info in enumerate(mensajes_a_procesar):
                if mensaje_info['procesado']:
                    logger.info(f"Mensaje {i+1} ya procesado, saltando...")
                    continue
                    
                logger.info(f"=== Procesando mensaje {i+1} de {len(mensajes_a_procesar)} (Fecha: {mensaje_info['fecha']}, Hora: {mensaje_info['hora']}, Asunto: {mensaje_info['asunto']}) ===")
                
                for intento in range(max_intentos):
                    try:
                        # Hacer clic en el mensaje
                        try:
                            logger.info(f"Haciendo clic en mensaje... (intento {intento+1})")
                            mensaje_info['elemento'].click()
                        except Exception as e:
                            logger.warning(f"Error en clic normal: {str(e)}")
                            logger.info("Intentando clic con JavaScript...")
                            self.driver.execute_script("arguments[0].click();", mensaje_info['elemento'])
                        
                        logger.info("Clic exitoso en el mensaje")
                        time.sleep(3)
                        
                        # Descargar el documento constancia
                        if self._descargar_documento_constancia():
                            logger.info(f"Documento para el mensaje {i+1} descargado exitosamente")
                            mensaje_info['procesado'] = True
                            mensajes_procesados += 1
                            
                            # Marcar el mensaje como procesado en el registro de seguimiento
                            tracker.marcar_como_procesado(ruc_empresa, mensaje_info['mensaje_id'])
                            
                            break  # Salir del bucle de intentos si la descarga fue exitosa
                        else:
                            logger.warning(f"Error al descargar el documento para el mensaje {i+1} - Intento {intento+1}")
                            if intento == max_intentos-1:  # Si es el último intento
                                logger.error(f"No se pudo descargar el documento para el mensaje {i+1} después de {max_intentos} intentos")
                    
                    except Exception as e:
                        logger.error(f"Error al procesar el mensaje {i+1}: {str(e)}")
                        if intento == max_intentos-1:  # Si es el último intento
                            logger.error(f"No se pudo procesar el mensaje {i+1} después de {max_intentos} intentos")
                    
                    # Si no es el último intento, volver a la lista de mensajes para reintentar
                    if intento < max_intentos-1:
                        try:
                            logger.info("Volviendo a la lista de mensajes para reintentar...")
                            self.driver.back()
                            time.sleep(3)
                            
                            # Recargar todos los elementos de la página
                            if not self._recargar_elementos_mensaje(mensajes_a_procesar, i):
                                logger.error("No se pudieron recargar los elementos de los mensajes")
                        except Exception as e:
                            logger.error(f"Error al volver a la lista de mensajes: {str(e)}")
                
                # Si no es el último mensaje, volver a la lista de mensajes para procesar el siguiente
                if i < len(mensajes_a_procesar)-1 and mensaje_info['procesado']:
                    try:
                        logger.info("Volviendo a la lista de mensajes para procesar el siguiente mensaje...")
                        self.driver.back()
                        time.sleep(3)
                        
                        # Recargar todos los elementos de la página
                        if not self._recargar_elementos_mensaje(mensajes_a_procesar, -1):  # -1 para recargar todos
                            logger.error("No se pudieron recargar los elementos de los mensajes")
                            # Intentar navegar al buzón nuevamente como última opción
                            self._navegar_a_buzon_notificaciones()
                            # Recargar mensajes después de navegar al buzón
                            self._recargar_mensajes_completo(mensajes_a_procesar, fechas_a_procesar)
                    except Exception as e:
                        logger.error(f"Error al volver a la lista de mensajes: {str(e)}")
                        # Intentar navegar al buzón nuevamente como última opción
                        self._navegar_a_buzon_notificaciones()
                        # Recargar mensajes después de navegar al buzón
                        self._recargar_mensajes_completo(mensajes_a_procesar, fechas_a_procesar)
            
            # Limpiar mensajes antiguos del registro (para mantenerlo manejable)
            tracker.limpiar_mensajes_antiguos(dias=30)
            
            logger.info(f"=== Procesamiento de mensajes completado. {mensajes_procesados} de {len(mensajes_a_procesar)} mensajes procesados exitosamente ===")
            return True, f"Procesados {mensajes_procesados} de {len(mensajes_a_procesar)} mensajes"
            
        except Exception as e:
            logger.error(f"Error al procesar mensajes: {str(e)}")
            # Capturar una imagen para diagnóstico
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join(config.LOGS_DIR, f"error_proceso_mensajes_{timestamp}.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Se guardó una captura de pantalla en: {screenshot_path}")
            return False, f"Error al procesar mensajes: {str(e)}"
        
    
    
    
    
    
    
    def _recargar_mensajes_completo(self, mensajes, fechas_a_procesar):
        """
        Función para recargar completamente la lista de mensajes, útil cuando la página cambia sustancialmente
        o necesitamos un reinicio completo de la detección de mensajes.
        
        Args:
            mensajes (list): Lista de mensajes a actualizar
            fechas_a_procesar (list): Lista de fechas a procesar en formato dd/mm/yyyy
            
        Returns:
            bool: True si se recargaron exitosamente, False en caso contrario
        """
        try:
            logger.info("=== Recargando completamente la lista de mensajes ===")
            
            # Marcar qué mensajes ya han sido procesados para no repetirlos
            procesados = [msg['procesado'] for msg in mensajes]
            
            # Buscar todos los mensajes y sus fechas de nuevo
            elementos_fecha = self.driver.find_elements(By.CLASS_NAME, "fecPublica")
            
            if not elementos_fecha:
                logger.warning("No se encontraron fechas de mensajes. Intentando buscar por XPath...")
                elementos_fecha = self.driver.find_elements(By.XPATH, "//div/small[contains(@class, 'text-muted')]")
            
            if not elementos_fecha:
                logger.error("No se pudieron encontrar fechas de mensajes.")
                return False
                
            logger.info(f"Se encontraron {len(elementos_fecha)} elementos de fecha.")
            
            # Limpiar y recargar mensajes con la información actual
            mensajes.clear()
            
            for i, elem_fecha in enumerate(elementos_fecha):
                texto_fecha = elem_fecha.text.strip()
                logger.info(f"Fecha del mensaje {i+1}: {texto_fecha}")
                
                # Extraer solo la parte de la fecha (sin la hora)
                partes_fecha = texto_fecha.split()
                if partes_fecha:
                    fecha_mensaje = partes_fecha[0]
                    hora_mensaje = partes_fecha[1] if len(partes_fecha) > 1 else ""
                    
                    if fecha_mensaje in fechas_a_procesar:
                        logger.info(f"¡Mensaje con fecha a procesar encontrado! Fecha: {fecha_mensaje}, Hora: {hora_mensaje}")
                        
                        # Buscar información adicional para identificación
                        try:
                            # Obtener el li que contiene el mensaje completo
                            li_padre = elem_fecha.find_element(By.XPATH, "./ancestor::li")
                            
                            # Intentar obtener el asunto
                            asunto = ""
                            try:
                                posibles_asuntos = li_padre.find_elements(By.TAG_NAME, "strong")
                                if posibles_asuntos:
                                    asunto = posibles_asuntos[0].text.strip()
                                else:
                                    posibles_asuntos = li_padre.find_elements(By.CLASS_NAME, "asunto")
                                    if posibles_asuntos:
                                        asunto = posibles_asuntos[0].text.strip()
                            except:
                                asunto = f"Mensaje-{i+1}"
                            
                            # Encontrar el elemento clickeable
                            mensaje_padre = None
                            try:
                                mensaje_padre = li_padre.find_element(By.TAG_NAME, "a")
                            except:
                                try:
                                    mensaje_padre = elem_fecha.find_element(By.XPATH, "./ancestor::a")
                                except:
                                    logger.warning(f"No se pudo encontrar el elemento clickeable para el mensaje {i+1}")
                                    continue
                            
                            # Verificar si este mensaje ya fue procesado comparando con la información anterior
                            procesado = False
                            if i < len(procesados) and procesados[i]:
                                procesado = True
                            
                            # Crear un identificador único para este mensaje
                            mensaje_id = f"{fecha_mensaje}_{hora_mensaje}_{asunto}_{li_padre.get_attribute('id') or ''}"
                            
                            if mensaje_padre:
                                mensajes.append({
                                    'fecha': fecha_mensaje,
                                    'hora': hora_mensaje,
                                    'elemento': mensaje_padre,
                                    'texto_hora': texto_fecha,
                                    'asunto': asunto,
                                    'html_id': li_padre.get_attribute('id') or "",
                                    'class_name': li_padre.get_attribute('class') or "",
                                    'indice': i,
                                    'procesado': procesado,
                                    'mensaje_id': mensaje_id
                                })
                        except Exception as e:
                            logger.error(f"Error al obtener detalles del mensaje {i+1}: {str(e)}")
            
            # Ordenar los mensajes por hora
            mensajes.sort(key=lambda x: f"{x['fecha']}_{x['hora']}")
            
            # Imprimir los mensajes encontrados
            logger.info(f"Se recargaron {len(mensajes)} mensajes para las fechas especificadas:")
            for i, msg in enumerate(mensajes):
                logger.info(f"  {i+1}. Fecha: {msg['fecha']}, Hora: {msg['hora']}, Asunto: {msg['asunto']}, Procesado: {msg['procesado']}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error al recargar completamente los mensajes: {str(e)}")
            return False

# Función para probar el módulo directamente
if __name__ == "__main__":
    # Configurar logging
    config.setup_logging()
    
    # Configuración de prueba
    print("=== Iniciando prueba de navegación web ===")
    from data_access import leer_datos_excel
    
    # Obtener datos de empresas
    empresas = leer_datos_excel()
    
    if empresas and len(empresas) > 0:
        empresas_procesadas = 0
        
        print(f"Se encontraron {len(empresas)} empresas para procesar:")
        for i, empresa in enumerate(empresas):
            print(f"{i+1}. {empresa['ruc']} - {empresa.get('razon_social', '')}")
        
        # Procesar todas las empresas
        for i, empresa in enumerate(empresas):
            print(f"\n{'-'*80}")
            print(f"Procesando empresa {i+1} de {len(empresas)}: {empresa['ruc']} - {empresa.get('razon_social', '')}")
            print(f"{'-'*80}\n")
            
            # Crear instancia del navegador para cada empresa
            navegador = SunatWebNavigator()
            
            # Ejecutar el proceso para esta empresa
            resultado = navegador.ejecutar_proceso_completo(empresa)
            
            if resultado:
                print(f"Proceso completado exitosamente para {empresa['ruc']}")
                empresas_procesadas += 1
            else:
                print(f"El proceso falló para {empresa['ruc']}")
                
        # Mostrar resumen final
        print(f"\n{'-'*80}")
        print(f"RESUMEN: Se procesaron {empresas_procesadas} de {len(empresas)} empresas exitosamente")
        print(f"{'-'*80}")
    else:
        print("No se pudieron obtener datos de empresas")
    
    

