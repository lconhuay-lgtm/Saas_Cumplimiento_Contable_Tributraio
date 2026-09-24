#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Módulo para seguimiento de mensajes procesados en la automatización SUNAT.
Este módulo se encarga de:
- Mantener un registro de mensajes ya procesados
- Evitar el procesamiento duplicado de mensajes
- Limpiar automáticamente registros antiguos
"""

import os
import json
import logging
from datetime import datetime, timedelta

# Configurar logger
logger = logging.getLogger('mensaje_tracker')

class MensajeTracker:
    """
    Clase para seguimiento de mensajes procesados para evitar duplicados.
    """
    
    def __init__(self, base_dir):
        """
        Inicializa el tracker de mensajes.
        
        Args:
            base_dir (str): Directorio base donde guardar el archivo de seguimiento
        """
        self.base_dir = base_dir
        self.registro_file = os.path.join(base_dir, "mensajes_procesados.json")
        self.mensajes_procesados = self._cargar_registro()
        
    def _cargar_registro(self):
        """
        Carga el registro de mensajes procesados.
        
        Returns:
            dict: Diccionario con mensajes procesados por RUC
        """
        try:
            if os.path.exists(self.registro_file):
                with open(self.registro_file, 'r', encoding='utf-8') as f:
                    registro = json.load(f)
                logger.info(f"Registro cargado con {sum(len(v) for v in registro.values())} mensajes procesados")
                return registro
            return {}
        except Exception as e:
            logger.error(f"Error al cargar registro de mensajes: {str(e)}")
            return {}
            
    def guardar_registro(self):
        """
        Guarda el registro de mensajes procesados.
        """
        try:
            # Crear carpeta si no existe
            os.makedirs(os.path.dirname(self.registro_file), exist_ok=True)
            
            with open(self.registro_file, 'w', encoding='utf-8') as f:
                json.dump(self.mensajes_procesados, f, ensure_ascii=False, indent=2)
            logger.info(f"Registro guardado correctamente en {self.registro_file}")
        except Exception as e:
            logger.error(f"Error al guardar registro de mensajes: {str(e)}")
            
    def es_mensaje_procesado(self, ruc, mensaje_id):
        """
        Verifica si un mensaje ya fue procesado.
        
        Args:
            ruc (str): RUC de la empresa
            mensaje_id (str): Identificador único del mensaje
            
        Returns:
            bool: True si el mensaje ya fue procesado, False en caso contrario
        """
        if ruc not in self.mensajes_procesados:
            self.mensajes_procesados[ruc] = []
            return False
            
        return mensaje_id in self.mensajes_procesados[ruc]
        
    def marcar_como_procesado(self, ruc, mensaje_id):
        """
        Marca un mensaje como procesado.
        
        Args:
            ruc (str): RUC de la empresa
            mensaje_id (str): Identificador único del mensaje
        """
        if ruc not in self.mensajes_procesados:
            self.mensajes_procesados[ruc] = []
            
        if mensaje_id not in self.mensajes_procesados[ruc]:
            self.mensajes_procesados[ruc].append(mensaje_id)
            self.guardar_registro()
            logger.info(f"Mensaje {mensaje_id} marcado como procesado para {ruc}")
            
    def limpiar_mensajes_antiguos(self, dias=30):
        """
        Limpia mensajes antiguos del registro para mantenerlo manejable.
        
        Args:
            dias (int): Número de días de antigüedad para eliminar registros
        """
        try:
            # Si el archivo tiene más de X días, reiniciarlo
            if os.path.exists(self.registro_file):
                fecha_mod = datetime.fromtimestamp(os.path.getmtime(self.registro_file))
                if (datetime.now() - fecha_mod).days > dias:
                    logger.info(f"Registro de mensajes tiene más de {dias} días, reiniciando...")
                    self.mensajes_procesados = {}
                    self.guardar_registro()
        except Exception as e:
            logger.error(f"Error al limpiar mensajes antiguos: {str(e)}")