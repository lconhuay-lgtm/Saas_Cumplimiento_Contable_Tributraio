#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fase R8 (refactor): metodos de deteccion post-login de SunatWebNavigator,
movidos TAL CUAL desde web_navigation.py -- ver autenticacion.py para la
explicacion completa del porque de este split.

Cubre: razon social, condicion de domicilio, estado del contribuyente
(Ficha RUC), y la deteccion de "flujo" (que pantalla post-login mostro
SUNAT esta vez -- la señal temprana de cambios en el portal que usa el
chequeo canario, Fase 3).
"""
import time
import logging

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

import config

logger = logging.getLogger('web_navigation')


class DeteccionEstadoMixin:
    """Deteccion post-login: razon social, condicion de domicilio, estado del contribuyente, flujo."""

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
    
