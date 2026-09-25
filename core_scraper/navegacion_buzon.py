#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fase R8 (refactor): metodos de navegacion y procesamiento del buzon de
SunatWebNavigator, movidos TAL CUAL desde web_navigation.py -- ver
autenticacion.py para la explicacion completa del porque de este split.

Cubre: entrar al buzon de notificaciones, recargar elementos de mensaje
(manejo de StaleElementReferenceException al recorrer la lista), y los dos
bucles principales de procesamiento (mensajes del dia / de un periodo de
dias hacia atras).
"""
import os
import time
import logging
from datetime import datetime, timedelta

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import config

logger = logging.getLogger('web_navigation')


class NavegacionBuzonMixin:
    """Navegacion del buzon: entrar, recorrer mensajes, procesar por dia/periodo."""

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

            # Estrategia 0: id estable del link real (confirmado en produccion,
            # 24/09, tras el rediseno de SUNAT -- el texto del link cambio de
            # "Buzón Notificaciones" a "Buzón Electrónico", por eso las
            # Estrategias 1 y 2 (XPath viejo y busqueda por ese texto viejo)
            # empezaron a fallar siempre y el flujo dependia por completo de
            # los fallbacks 3/4, que son mas lentos y no siempre confiables
            # (a veces terminan en una vista sin la lista de mensajes
            # cargada). id="aOpcionBuzon" es el selector mas estable posible.
            try:
                logger.info("Estrategia 0: Buscando Buzón Electrónico por id 'aOpcionBuzon'...")
                buzon_elemento = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.ID, "aOpcionBuzon"))
                )
                buzon_elemento.click()
                logger.info("Clic exitoso usando Estrategia 0")
                time.sleep(3)
                return True
            except Exception as e:
                logger.warning(f"Estrategia 0 falló: {str(e)}")

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

    def _buscar_en_default_y_iframes(self, buscar_fn):
        """
        Prueba buscar_fn(self.driver) primero en default_content, y si no
        encuentra nada recorre cada iframe de primer nivel -- mismo patron
        ya usado en _escanear_mensajes (adapter.py) para el Buzon
        Notificaciones, confirmado en vivo (25/09/2026) que el Buzon
        Mensajes vive dentro de un iframe (no siempre el mismo indice,
        asi que hay que recorrerlos en vez de asumir uno fijo). Deja el
        driver posicionado en el contexto donde SI encontro algo.

        Returns:
            El resultado de buscar_fn si algo se encontro, o None.
        """
        self.driver.switch_to.default_content()
        resultado = buscar_fn(self.driver)
        if resultado:
            return resultado

        for iframe in self.driver.find_elements(By.TAG_NAME, "iframe"):
            try:
                self.driver.switch_to.frame(iframe)
            except Exception:
                self.driver.switch_to.default_content()
                continue
            resultado = buscar_fn(self.driver)
            if resultado:
                return resultado
            self.driver.switch_to.default_content()

        return None

    def _navegar_a_buzon_mensajes(self):
        """
        Navega a "Buzón Mensajes" -- bandeja SEPARADA de "Buzón
        Notificaciones" dentro del mismo Buzon Electronico (confirmado en
        vivo 25/09/2026: enlace de texto "Buzón Mensajes" en el sidebar,
        en el mismo iframe donde vive la lista de Notificaciones). A
        diferencia de Notificaciones, esta bandeja no tiene PDF adjunto en
        general -- el contenido completo esta en el cuerpo del mensaje.

        Debe llamarse DESPUES de _navegar_a_buzon_notificaciones() (o de
        cualquier punto donde ya se este dentro del Buzon Electronico),
        nunca antes -- el enlace de "Buzón Mensajes" solo existe una vez
        que se entro al Buzon.
        """
        try:
            logger.info("Navegando a Buzón Mensajes...")

            def buscar_link_mensajes(driver):
                estrategias = [
                    (By.PARTIAL_LINK_TEXT, "Buzón Mensajes"),
                    (By.PARTIAL_LINK_TEXT, "Buzon Mensajes"),
                    (By.XPATH, "//a[contains(text(), 'Mensajes')]"),
                ]
                for by, valor in estrategias:
                    try:
                        el = driver.find_element(by, valor)
                        if el:
                            return el
                    except Exception:
                        continue
                return None

            elemento = self._buscar_en_default_y_iframes(buscar_link_mensajes)
            if elemento is None:
                logger.warning("No se encontro el enlace 'Buzón Mensajes'.")
                return False

            try:
                elemento.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", elemento)
            time.sleep(3)
            logger.info("Clic exitoso en 'Buzón Mensajes'")
            return True
        except Exception as e:
            logger.error(f"Error al navegar a Buzón Mensajes: {str(e)}")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join(config.LOGS_DIR, f"error_buzon_mensajes_{timestamp}.png")
            try:
                self.driver.save_screenshot(screenshot_path)
            except Exception:
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

