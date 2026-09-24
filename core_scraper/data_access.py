#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Módulo para el acceso a datos: lectura de Excel y gestión de archivos/carpetas.
"""

import os
import re
import logging
import shutil
import pandas as pd
from datetime import datetime, timedelta

# Importar configuración
from config import BASE_DIR, EXCEL_PATH, MAX_ANTIGUEDAD_CARPETAS

# Configurar logger
logger = logging.getLogger('data_access')

def leer_datos_excel():
    """
    Lee los datos del archivo Excel con las credenciales usando la tabla "Sol"
    Retorna una lista de diccionarios con los datos de cada empresa
    """
    try:
        # Usar la ruta del Excel desde la configuración
        ruta_excel = EXCEL_PATH
        logger.info(f"Leyendo datos desde: {ruta_excel}")
        
        # Verificar si el archivo existe
        if not os.path.exists(ruta_excel):
            logger.error(f"ERROR: El archivo {ruta_excel} no existe.")
            return None
            
        # Mostrar información sobre el archivo
        logger.info(f"Tamaño del archivo: {os.path.getsize(ruta_excel)} bytes")
        
        try:
            # Intentar leer la tabla "Sol" directamente
            df = pd.read_excel(ruta_excel, sheet_name=0, table="Sol")
            logger.info("Tabla 'Sol' encontrada y leída correctamente")
        except:
            # Si falla, intentar leer de forma convencional (con encabezados en la primera fila)
            logger.warning("No se pudo leer la tabla 'Sol', intentando leer con encabezados estándar...")
            df = pd.read_excel(ruta_excel, sheet_name=0)
        
        logger.info(f"Excel leído correctamente: {df.shape[0]} filas x {df.shape[1]} columnas")
        logger.debug("Primeras filas del DataFrame:")
        logger.debug(df.head())
        
        # Identificar las columnas correctas por nombre (caso insensible)
        columnas = {}
        for col in df.columns:
            if isinstance(col, str):
                if 'ruc' in col.lower():
                    columnas['ruc'] = col
                elif 'contribuyente' in col.lower() or 'razon' in col.lower():
                    columnas['razon_social'] = col
                elif 'usuario' in col.lower() or 'user' in col.lower():
                    columnas['usuario'] = col
                elif 'password' in col.lower() or 'clave' in col.lower() or 'contraseña' in col.lower():
                    columnas['clave'] = col
        
        # Verificar si se encontraron todas las columnas necesarias
        columnas_faltantes = []
        for campo in ['ruc', 'usuario', 'clave']:
            if campo not in columnas:
                columnas_faltantes.append(campo)
        
        if columnas_faltantes:
            logger.error(f"ERROR: No se encontraron las siguientes columnas requeridas: {', '.join(columnas_faltantes)}")
            logger.error(f"Columnas encontradas: {list(df.columns)}")
            return None
            
        # Si no se encontró columna de razón social, usar una columna vacía
        if 'razon_social' not in columnas:
            logger.warning("ADVERTENCIA: No se encontró columna de razón social. Se usará un valor vacío.")
            df['RAZON_SOCIAL_TEMP'] = ""
            columnas['razon_social'] = 'RAZON_SOCIAL_TEMP'
            
        # Crear lista de diccionarios con los datos de cada empresa
        datos_empresas = []
        
        # Iterar sobre cada fila del DataFrame
        for i, row in df.iterrows():
            try:
                # Extraer valores usando los nombres de columna identificados
                ruc_val = row[columnas['ruc']]
                razon_social_val = row[columnas['razon_social']]
                usuario_val = row[columnas['usuario']]
                clave_val = row[columnas['clave']]
                
                # Convertir valores a string con manejo robusto de errores
                try:
                    # Para RUC (intentar convertir a entero si es posible)
                    if pd.isna(ruc_val):
                        ruc = ""
                    elif isinstance(ruc_val, (int, float)) and not pd.isna(ruc_val):
                        ruc = str(int(ruc_val))  # Quitar decimales si es número
                    else:
                        ruc = str(ruc_val).strip()
                except:
                    ruc = str(ruc_val).strip()
                
                # Para razón social
                razon_social = str(razon_social_val).strip() if not pd.isna(razon_social_val) else ""
                
                # Para usuario (intentar convertir a entero si es posible)
                try:
                    if pd.isna(usuario_val):
                        usuario = ""
                    elif isinstance(usuario_val, (int, float)) and not pd.isna(usuario_val):
                        usuario = str(int(usuario_val))  # Quitar decimales si es número
                    else:
                        usuario = str(usuario_val).strip()
                except:
                    usuario = str(usuario_val).strip()
                
                # Para clave
                clave = str(clave_val).strip() if not pd.isna(clave_val) else ""
                
                logger.info(f"Datos extraídos: RUC={ruc}, Razón Social={razon_social}, Usuario={usuario}, Clave={'*'*len(clave)}")
                
                # Verificar que los datos obligatorios estén presentes
                if ruc and usuario and clave:
                    datos_empresas.append({
                        'ruc': ruc,
                        'razon_social': razon_social,
                        'usuario': usuario,
                        'clave': clave
                    })
                    logger.info(f"Empresa {len(datos_empresas)} agregada correctamente")
                else:
                    logger.warning(f"Fila {i+1} incompleta, saltando (faltan datos obligatorios)")
            except Exception as e:
                logger.error(f"Error al procesar fila {i+1}: {str(e)}")
                continue
        
        logger.info(f"Se cargaron {len(datos_empresas)} empresas desde el Excel")
        return datos_empresas
        
    except Exception as e:
        logger.error(f"Error al leer datos del Excel: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def crear_estructura_carpetas(empresa):
    """
    Crea la estructura de carpetas para guardar los archivos:
    - Carpeta base
    - Subcarpeta con el RUC y razón social ("RUC - RAZON SOCIAL")
    - Subcarpeta con la fecha actual (dd.mm.yyyy)
    
    Retorna la ruta completa de la carpeta donde se guardarán los archivos
    """
    try:
        # Asegurar que la carpeta base existe
        if not os.path.exists(BASE_DIR):
            os.makedirs(BASE_DIR)
            logger.info(f"Carpeta base creada: {BASE_DIR}")
        
        # Crear nombre de carpeta con RUC y razón social
        ruc = empresa['ruc']
        razon_social = empresa['razon_social']
        # Eliminar caracteres no válidos para nombres de carpeta
        razon_social_limpia = re.sub(r'[\\/*?:"<>|]', "", razon_social)
        
        nombre_carpeta_empresa = f"{ruc} - {razon_social_limpia}"
        carpeta_empresa = os.path.join(BASE_DIR, nombre_carpeta_empresa)
        
        # Crear subcarpeta con el RUC y razón social si no existe
        if not os.path.exists(carpeta_empresa):
            os.makedirs(carpeta_empresa)
            logger.info(f"Carpeta empresa creada: {carpeta_empresa}")
        
        # Crear subcarpeta con la fecha actual
        fecha_actual = datetime.now().strftime("%d.%m.%Y")
        carpeta_fecha = os.path.join(carpeta_empresa, fecha_actual)
        if not os.path.exists(carpeta_fecha):
            os.makedirs(carpeta_fecha)
            logger.info(f"Carpeta de fecha creada: {carpeta_fecha}")
            
        # Limpiar carpetas antiguas (más de un año)
        limpiar_carpetas_antiguas(carpeta_empresa)
            
        return carpeta_fecha
        
    except Exception as e:
        logger.error(f"Error al crear estructura de carpetas: {str(e)}")
        # En caso de error, usar la carpeta de descargas predeterminada
        return os.path.join(os.path.expanduser("~"), "Downloads")


def limpiar_carpetas_antiguas(carpeta_empresa):
    """
    Elimina las carpetas de fecha que tienen más de un año de antigüedad
    """
    try:
        logger.info("Verificando carpetas antiguas para eliminar...")
        
        # Fecha límite (1 año atrás desde hoy)
        fecha_limite = datetime.now() - timedelta(days=MAX_ANTIGUEDAD_CARPETAS)
        
        # Listar todas las carpetas dentro de la carpeta empresa
        for nombre_carpeta in os.listdir(carpeta_empresa):
            ruta_carpeta = os.path.join(carpeta_empresa, nombre_carpeta)
            
            # Verificar si es una carpeta y tiene el formato de fecha esperado (dd.mm.yyyy)
            if os.path.isdir(ruta_carpeta) and re.match(r'\d{2}\.\d{2}\.\d{4}', nombre_carpeta):
                try:
                    # Convertir el nombre de la carpeta a objeto fecha
                    fecha_carpeta = datetime.strptime(nombre_carpeta, "%d.%m.%Y")
                    
                    # Comparar con la fecha límite
                    if fecha_carpeta < fecha_limite:
                        logger.info(f"Eliminando carpeta antigua: {nombre_carpeta}")
                        shutil.rmtree(ruta_carpeta)
                except Exception as e:
                    logger.error(f"Error al procesar carpeta {nombre_carpeta}: {str(e)}")
                    continue
        
        logger.info("Limpieza de carpetas antiguas completada")
        
    except Exception as e:
        logger.error(f"Error al limpiar carpetas antiguas: {str(e)}")


def obtener_archivos_descargados(carpeta_descarga):
    """
    Obtiene una lista de los archivos descargados en la carpeta especificada,
    incluyendo PDFs y archivos temporales que podrían ser PDFs.
    
    Args:
        carpeta_descarga (str): Ruta a la carpeta donde se descargaron los archivos
        
    Returns:
        list: Lista de rutas completas a los archivos
    """
    try:
        if not os.path.exists(carpeta_descarga):
            logger.warning(f"La carpeta {carpeta_descarga} no existe")
            return []
        
        # Listar todos los archivos en la carpeta
        logger.info(f"Buscando archivos en: {carpeta_descarga}")
        archivos = []
        
        for f in os.listdir(carpeta_descarga):
            ruta_completa = os.path.join(carpeta_descarga, f)
            if os.path.isfile(ruta_completa):
                tamaño = os.path.getsize(ruta_completa)
                fecha_mod = datetime.fromtimestamp(os.path.getmtime(ruta_completa)).strftime("%Y-%m-%d %H:%M:%S")
                logger.info(f"  - {f} (tamaño: {tamaño} bytes, modificado: {fecha_mod})")
                
                # Incluir PDFs explícitos
                if f.lower().endswith('.pdf'):
                    archivos.append(ruta_completa)
                    logger.info(f"  → Archivo PDF detectado: {f}")
                # Incluir archivos temporales o sin extensión que tengan tamaño razonable
                elif tamaño > 5000:  # Más de 5KB
                    # Intentar verificar si es un PDF
                    try:
                        with open(ruta_completa, 'rb') as file:
                            header = file.read(4)
                            if header == b'%PDF':
                                archivos.append(ruta_completa)
                                logger.info(f"  → Archivo PDF detectado por cabecera: {f}")
                            elif tamaño > 30000:  # Más de 30KB
                                # Si es grande, incluirlo aunque no tenga la cabecera PDF
                                archivos.append(ruta_completa)
                                logger.info(f"  → Posible PDF (archivo grande): {f}")
                    except:
                        # En caso de error, incluirlo si es grande
                        if tamaño > 50000:  # Más de 50KB
                            archivos.append(ruta_completa)
                            logger.info(f"  → Incluido a pesar de error (archivo grande): {f}")
        
        logger.info(f"Se encontraron {len(archivos)} archivos para procesar en {carpeta_descarga}")
        
        # Ordenar por fecha de creación (más reciente primero)
        archivos.sort(key=os.path.getctime, reverse=True)
        
        return archivos
    
    except Exception as e:
        logger.error(f"Error al obtener archivos descargados: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return []


def mover_archivo_descargado(ruta_archivo, carpeta_destino):
    """
    Mueve un archivo descargado a la carpeta de destino deseada
    """
    try:
        nombre_archivo = os.path.basename(ruta_archivo)
        ruta_destino = os.path.join(carpeta_destino, nombre_archivo)
        
        # Verificar si el archivo ya existe en el destino
        if os.path.exists(ruta_destino):
            # Agregar timestamp al nombre para evitar sobrescritura
            nombre_base, extension = os.path.splitext(nombre_archivo)
            timestamp = datetime.now().strftime("%H%M%S")
            nuevo_nombre = f"{nombre_base}_{timestamp}{extension}"
            ruta_destino = os.path.join(carpeta_destino, nuevo_nombre)
        
        # Mover el archivo
        shutil.move(ruta_archivo, ruta_destino)
        logger.info(f"Archivo movido a: {ruta_destino}")
        return True
        
    except Exception as e:
        logger.error(f"Error al mover archivo: {str(e)}")
        return False

def limpiar_archivos_temporales(carpeta_descarga):
    """
    Limpia archivos temporales y archivos duplicados en la carpeta de descarga.
    
    Args:
        carpeta_descarga (str): Ruta a la carpeta donde se descargan los archivos
    """
    try:
        if not os.path.exists(carpeta_descarga):
            return
            
        logger.info(f"Limpiando archivos temporales en {carpeta_descarga}")
        
        # Buscar archivos con extensiones temporales
        archivos_temp = []
        for archivo in os.listdir(carpeta_descarga):
            ruta_completa = os.path.join(carpeta_descarga, archivo)
            if os.path.isfile(ruta_completa):
                # Verificar si es un archivo temporal
                if archivo.endswith('.tmp') or archivo.endswith('.crdownload'):
                    archivos_temp.append(ruta_completa)
                    
        # Eliminar los archivos temporales
        for archivo in archivos_temp:
            try:
                os.remove(archivo)
                logger.info(f"Archivo temporal eliminado: {os.path.basename(archivo)}")
            except Exception as e:
                logger.error(f"Error al eliminar archivo temporal {os.path.basename(archivo)}: {str(e)}")
                
    except Exception as e:
        logger.error(f"Error al limpiar archivos temporales: {str(e)}")


# Función para probar el módulo directamente
if __name__ == "__main__":
    from config import setup_logging
    setup_logging()
    
    # Probar lectura de datos
    print("=== Probando lectura de datos ===")
    empresas = leer_datos_excel()
    if empresas:
        print(f"Se leyeron {len(empresas)} empresas")
        
        # Probar creación de carpetas
        if len(empresas) > 0:
            print("\n=== Probando creación de carpetas ===")
            carpeta = crear_estructura_carpetas(empresas[0])
            print(f"Carpeta creada: {carpeta}")
    else:
        print("No se pudieron leer datos del Excel")