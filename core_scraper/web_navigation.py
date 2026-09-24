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

Fase R8 (refactor, plan de remediacion, 24/09): este archivo tenia 2178
lineas en una sola clase -- el componente mas grande Y el mas fragil (se
rompe cada vez que SUNAT cambia algo en su portal), una combinacion que
hacia lento cualquier diagnostico. Se dividio por responsabilidad en 5
mixins (autenticacion.py, deteccion_estado.py, navegacion_buzon.py,
descarga_documentos.py, diagnostico.py) que SunatWebNavigator hereda --
CADA METODO SE MOVIO TAL CUAL, sin cambiar una sola linea de logica, solo
de archivo. `self.driver`, `self.wait`, `self.empresa`, etc. siguen siendo
exactamente los mismos atributos de instancia de siempre; los mixins no
necesitan (ni definen) su propio __init__, confian en que
SunatWebNavigator.__init__ ya los dejo listos antes de que se llame
cualquier metodo.

Nada fuera de este archivo tiene que cambiar: `from web_navigation import
SunatWebNavigator` sigue funcionando identico (ver adapter.py y los
scripts de diagnostico en backend/).

Verificado despues del split: mismo login real contra la cuenta canario
(RUC 10711864496) exitoso, misma suite pytest, mismo listado de metodos
publicos en la clase final que antes del refactor.
"""
import time
import logging

import config

from autenticacion import AutenticacionMixin
from deteccion_estado import DeteccionEstadoMixin
from navegacion_buzon import NavegacionBuzonMixin
from descarga_documentos import DescargaDocumentosMixin
from diagnostico import DiagnosticoMixin

# Configurar logger
logger = logging.getLogger('web_navigation')


class SunatWebNavigator(
    AutenticacionMixin,
    DeteccionEstadoMixin,
    NavegacionBuzonMixin,
    DescargaDocumentosMixin,
    DiagnosticoMixin,
):
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
    
    

