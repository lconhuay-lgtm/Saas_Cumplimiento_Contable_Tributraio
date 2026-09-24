#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fase R8 (refactor, plan de remediacion): metodos de sesion/autenticacion de
SunatWebNavigator, movidos aca TAL CUAL desde web_navigation.py -- sin
cambiar una sola linea de logica, solo reorganizando por responsabilidad
(este archivo era, junto con el resto, un solo web_navigation.py de 2178
lineas). SunatWebNavigator (en web_navigation.py) hereda de esta mixin
igual que de las demas -- todo `self.driver`, `self.wait`, etc. sigue
siendo el mismo objeto de siempre, nada de esto cambia en tiempo de
ejecucion.

Cubre: iniciar/cerrar el navegador, los clicks hasta llegar al login,
ingresar credenciales, y cerrar el comunicado que a veces aparece
despues de loguearse.
"""
import time
import logging

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException

import config
from config import CHROME_PREFS
from data_access import crear_estructura_carpetas

logger = logging.getLogger('web_navigation')


class AutenticacionMixin:
    """Sesion: iniciar/cerrar navegador, login, credenciales, comunicado post-login."""

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

