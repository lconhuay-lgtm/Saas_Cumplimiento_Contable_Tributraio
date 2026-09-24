#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Configuracion del motor de automatizacion SUNAT (core_scraper).

Adaptado del config.py original de Sunat_Aut_Brian para correr dentro de un
contenedor Linux (Docker) en vez de un escritorio Windows: las rutas ya no
estan hardcodeadas (J:\\..., C:\\...) sino que vienen de variables de entorno,
con valores por defecto razonables para desarrollo local. Las variables de
correo/Excel del script original NO viven aqui -- ese trabajo ahora lo hace
el backend (lee empresas de Postgres, envia notificaciones por su cuenta).
"""

import os
import logging
from datetime import datetime

# Configuracion general (igual que el original, ya validado en produccion)
MAX_INTENTOS = int(os.environ.get('SUNAT_MAX_INTENTOS', 3))
TIEMPO_ESPERA_DEFAULT = int(os.environ.get('SUNAT_TIEMPO_ESPERA', 10))  # segundos
MAX_ANTIGUEDAD_CARPETAS = int(os.environ.get('SUNAT_MAX_ANTIGUEDAD_DIAS', 365))
DIAS_ATRAS_DEFAULT = int(os.environ.get('SUNAT_DIAS_ATRAS', 5))

# Directorio de trabajo dentro del contenedor (descargas temporales, capturas
# de error). En Fase 1 esto se reemplaza por almacenamiento de objetos (S3);
# por ahora es una carpeta local montada como volumen.
BASE_DIR = os.environ.get('SUNAT_BASE_DIR', '/data/sunat')
LOGS_DIR = os.environ.get('SUNAT_LOGS_DIR', os.path.join(BASE_DIR, 'logs'))

# Compatibilidad con data_access.py: la lectura de Excel (leer_datos_excel)
# queda en desuso en este proyecto -- las empresas ahora viven en Postgres,
# gestionadas por el backend -- pero se deja la variable para no romper el
# import. EXCEL_PATH vacio simplemente hace que esa funcion falle si alguien
# la llama por error, en vez de lanzar un ImportError silencioso.
EXCEL_PATH = os.environ.get('SUNAT_EXCEL_PATH', '')

# URLs
URL_SUNAT = "https://www.sunat.gob.pe/"

# Configuracion del navegador (igual que el original, incluye --guest para
# perfiles limpios en cada sesion)
CHROME_OPTIONS = [
    '--disable-popup-blocking',
    '--disable-notifications',
    '--disable-extensions',
    '--no-sandbox',
    '--disable-gpu',
    '--guest',
]

CHROME_PREFS = {
    'credentials_enable_service': False,
    'profile.password_manager_enabled': False,
}

# En Docker/Linux, Chromium no siempre queda donde Selenium lo busca por
# defecto -- estas variables permiten apuntarlo explicitamente. En Windows
# (uso original del script) se dejan vacias y Selenium detecta Chrome solo,
# sin cambiar nada del comportamiento ya validado ahi.
CHROME_BINARY_LOCATION = os.environ.get('CHROME_BINARY_LOCATION', '')
CHROMEDRIVER_PATH = os.environ.get('CHROMEDRIVER_PATH', '')

# Si se ejecuta headless por defecto (los endpoints/worker pueden sobrescribir
# esto por llamada, esto es solo el default de conveniencia).
HEADLESS_DEFAULT = os.environ.get('SUNAT_HEADLESS', 'false').lower() == 'true'


def setup_logging():
    """Configura el logging del motor. Igual patron que el script original."""
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR, exist_ok=True)

    log_filename = os.path.join(LOGS_DIR, f"sunat_auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )

    for logger_name in ['web_navigation', 'data_access', 'mensaje_tracker']:
        logging.getLogger(logger_name).setLevel(logging.INFO)

    logging.getLogger('selenium').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

    logging.info(f"Logging configurado. Archivo de log: {log_filename}")
    return log_filename


def crear_estructura_base():
    """Crea la estructura basica de carpetas si no existe."""
    for carpeta in (BASE_DIR, LOGS_DIR):
        if not os.path.exists(carpeta):
            try:
                os.makedirs(carpeta, exist_ok=True)
                logging.info(f"Carpeta creada: {carpeta}")
            except Exception as e:
                logging.error(f"Error al crear carpeta {carpeta}: {str(e)}")


# Crear estructura al importar el modulo (igual que el original)
crear_estructura_base()
