#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Utilidad SOLO para pruebas -- NO es parte de la aplicacion ni se llama desde
ningun endpoint. probar_fase2.py la invoca asi:

    docker-compose exec -T backend python _sembrar_prueba_fase2.py <empresa_id>

Inserta 2 mensajes de prueba y un ConsultaJob "completado" para esa empresa,
sin necesitar una consulta real a SUNAT. Sirve para probar rapido la logica
nueva de Fase 2 (conteo de pendientes, marcar leido, correo de resumen)
sin depender de tiempos de login real ni del estado del buzon en SUNAT en
ese momento.
"""
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

from app.database import SessionLocal
from app.models import MensajeBuzon, ConsultaJob


def main():
    if len(sys.argv) != 2:
        print("Uso: python _sembrar_prueba_fase2.py <empresa_id>")
        sys.exit(1)
    empresa_id = sys.argv[1]

    db = SessionLocal()
    try:
        sufijo = uuid.uuid4().hex[:8]
        db.add(MensajeBuzon(
            empresa_id=empresa_id,
            mensaje_externo_id=f"prueba-fase2-{sufijo}-1",
            fecha_publicacion=datetime.now(timezone.utc),
            asunto="[PRUEBA FASE 2] Notificacion de prueba 1",
        ))
        db.add(MensajeBuzon(
            empresa_id=empresa_id,
            mensaje_externo_id=f"prueba-fase2-{sufijo}-2",
            fecha_publicacion=datetime.now(timezone.utc),
            asunto="[PRUEBA FASE 2] Notificacion de prueba 2",
        ))
        db.add(ConsultaJob(
            empresa_id=empresa_id,
            solicitado_por=None,
            estado="completado",
            mensajes_nuevos=2,
            notificado=False,
            finalizado_en=datetime.now(timezone.utc),
        ))
        db.commit()
        print("OK: 2 mensajes de prueba + 1 job 'completado' insertados")
    finally:
        db.close()


if __name__ == "__main__":
    main()
