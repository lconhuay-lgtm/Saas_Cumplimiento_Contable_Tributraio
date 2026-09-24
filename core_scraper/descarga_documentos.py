#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fase R8 (refactor): metodos de descarga de documentos de SunatWebNavigator,
movidos TAL CUAL desde web_navigation.py -- ver autenticacion.py para la
explicacion completa del porque de este split.

Cubre: esperar a que termine una descarga, descargar el PDF de un mensaje,
y descargar la constancia/documento asociado.
"""
import os
import time
import logging
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger('web_navigation')


class DescargaDocumentosMixin:
    """Descarga de documentos: esperar descarga, PDF de mensaje, constancia."""

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

                    # Ejecutar el JavaScript del propio link TAL CUAL, en vez
                    # de parsear los parametros a mano y reconstruir la
                    # llamada asumiendo siempre 3 (id_archivo, 0, cod_mensaje)
                    # -- confirmado en produccion (24/09) que algunas
                    # notificaciones (ej. "Resolucion Coactiva Nro: ...")
                    # traen goArchivoDescarga con solo 2 parametros
                    # (sin cod_mensaje), y el indice fijo params[2] reventaba
                    # con IndexError, dejando esos mensajes sin PDF para
                    # siempre. Replicar el href original funciona sin
                    # importar cuantos argumentos tenga esta vez.
                    try:
                        js = href[len("javascript:"):] if href.startswith("javascript:") else href
                        logger.info(f"Ejecutando: {js}")
                        self.driver.execute_script(js)
                        
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
