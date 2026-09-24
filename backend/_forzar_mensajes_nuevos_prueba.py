#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Utilidad SOLO para pruebas -- NO es parte de la aplicacion.

Borra los N mensajes reales mas recientes de una empresa para que, en la
proxima consulta real, el adapter los vea como "nuevos" (no estan en
ids_conocidos) y por lo tanto intente descargar su documento.

Uso:
    docker-compose exec -T backend python _forzar_mensajes_nuevos_prueba.py <empresa_id> [cantidad]
"""
import sys

sys.path.insert(0, "/app/backend")

from app.database import SessionLocal
from app.models import MensajeBuzon


def main():
    if len(sys.argv) < 2:
        print("Uso: python _forzar_mensajes_nuevos_prueba.py <empresa_id> [cantidad]")
        sys.exit(1)
    empresa_id = sys.argv[1]
    cantidad = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    db = SessionLocal()
    try:
        sinteticos = (
            db.query(MensajeBuzon)
            .filter(
                MensajeBuzon.empresa_id == empresa_id,
                MensajeBuzon.mensaje_externo_id.like("prueba-fase2-%"),
            )
            .all()
        )
        if sinteticos:
            print(f"Limpiando {len(sinteticos)} mensaje(s) sintetico(s) de pruebas anteriores (no son de SUNAT real)...")
            for s in sinteticos:
                db.delete(s)
            db.commit()

        mensajes = (
            db.query(MensajeBuzon)
            .filter(MensajeBuzon.empresa_id == empresa_id)
            .order_by(MensajeBuzon.fecha_publicacion.desc())
            .limit(cantidad)
            .all()
        )
        if not mensajes:
            print("Esa empresa no tiene mensajes reales guardados todavia -- nada que forzar.")
            return
        for m in mensajes:
            print(f"Borrando (para que vuelva a aparecer como nuevo): {m.asunto}")
            db.delete(m)
        db.commit()
        print(f"OK: {len(mensajes)} mensaje(s) borrado(s). La proxima consulta los volvera a traer y descargara su PDF.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
