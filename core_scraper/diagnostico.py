#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fase R8 (refactor): metodo de diagnostico de SunatWebNavigator, movido TAL
CUAL desde web_navigation.py -- ver autenticacion.py para la explicacion
completa del porque de este split.

Cubre: guardar captura de pantalla + HTML de la pagina en el momento de un
error, para poder diagnosticar sin haber visto la sesion en vivo (headless/
worker) -- ver PLAYBOOK_FALLOS_SUNAT.md para como se usa esto en la
practica.
"""
import os
import logging
from datetime import datetime

import config

logger = logging.getLogger('web_navigation')


class DiagnosticoMixin:
    """Diagnostico: captura de pantalla + HTML en el momento de un error."""

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

