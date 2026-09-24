#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de DIAGNOSTICO de solo lectura -- NO abre navegador, NO entra a
SUNAT, NO toca produccion. Junta en un solo lugar la evidencia que ya
deberia existir sobre por que el chequeo canario esta fallando (paso 1-3
del playbook, ver PLAYBOOK_FALLOS_SUNAT.md):

1. Los ultimos registros de canario_checks (empresa, exito, flujo_detectado,
   duracion, y el mensaje de error corto) -- el detalle de cada chequeo
   canario reciente.
2. Los ultimos errores de consultas_jobs (consultas normales de clientes) --
   para confirmar si el problema es SOLO del canario o TAMBIEN de clientes
   reales. Si solo el canario falla, es mas probable que sea un problema
   puntual de esa cuenta (credenciales, RUC de baja, etc.) que un cambio
   real del portal.
3. Los archivos de captura de pantalla/HTML mas recientes en
   sunat_data/logs/ -- web_navigation.py ya los genera automaticamente en
   cada fallo real (ver _guardar_captura_error() en web_navigation.py,
   llamada desde _hacer_clicks_sunat y _navegar_a_buzon_notificaciones), asi
   que si el canario fallo de verdad contra SUNAT ya deberian existir sin
   tener que volver a correr nada.

Correrlo (PowerShell, desde la carpeta buzon-saas):
    docker-compose exec -T backend python diagnosticar_canario.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models import CanarioCheck, ConsultaJob, Empresa

import config as core_config  # config.py de core_scraper (ya esta en PYTHONPATH)


def _fmt(dt):
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def mostrar_canario(db, limite=15):
    print("=" * 70)
    print(f"ULTIMOS {limite} CHEQUEOS CANARIO (canario_checks)")
    print("=" * 70)
    filas = (
        db.query(CanarioCheck, Empresa)
        .join(Empresa, Empresa.id == CanarioCheck.empresa_id)
        .order_by(CanarioCheck.ejecutado_en.desc())
        .limit(limite)
        .all()
    )
    if not filas:
        print("No hay ningun CanarioCheck guardado todavia.")
        return
    for check, empresa in filas:
        estado = "OK   " if check.exito else "FALLO"
        print(
            f"[{estado}] {_fmt(check.ejecutado_en)}  {empresa.ruc} ({empresa.razon_social})  "
            f"flujo={check.flujo_detectado or '-'}  duracion={check.duracion_seg}s"
        )
        if not check.exito:
            print(f"          error: {check.error}")


def mostrar_consultas_recientes(db, limite=15):
    print()
    print("=" * 70)
    print(f"ULTIMOS {limite} ERRORES DE CONSULTAS NORMALES (consultas_jobs, estado='error')")
    print("=" * 70)
    filas = (
        db.query(ConsultaJob, Empresa)
        .join(Empresa, Empresa.id == ConsultaJob.empresa_id)
        .filter(ConsultaJob.estado == "error")
        .order_by(ConsultaJob.finalizado_en.desc())
        .limit(limite)
        .all()
    )
    if not filas:
        print("Ninguna consulta normal registro error recientemente.")
        print("-> Si el canario SI esta fallando pero esto esta vacio, es una buena senal")
        print("   de que el problema es puntual de la cuenta canario (credenciales, RUC de")
        print("   baja, etc.), no necesariamente un cambio general del portal de SUNAT.")
        return
    for job, empresa in filas:
        print(f"[ERROR] {_fmt(job.finalizado_en)}  {empresa.ruc} ({empresa.razon_social})  etapa={job.etapa or '-'}")
        print(f"        error: {job.error}")


def mostrar_evidencia_reciente(cantidad=20):
    print()
    print("=" * 70)
    print(f"ULTIMOS {cantidad} ARCHIVOS DE EVIDENCIA EN {core_config.LOGS_DIR}")
    print("=" * 70)
    logs_dir = core_config.LOGS_DIR
    if not os.path.isdir(logs_dir):
        print(f"La carpeta {logs_dir} no existe todavia (nunca se genero ninguna captura de error).")
        return
    archivos = [
        os.path.join(logs_dir, f) for f in os.listdir(logs_dir)
        if f.lower().endswith((".png", ".html", ".log"))
    ]
    if not archivos:
        print(f"No hay archivos .png/.html/.log en {logs_dir} todavia.")
        return
    archivos.sort(key=os.path.getmtime, reverse=True)
    for ruta in archivos[:cantidad]:
        mtime = datetime.fromtimestamp(os.path.getmtime(ruta))
        print(f"  {mtime.strftime('%Y-%m-%d %H:%M:%S')}  {ruta}")
    print()
    print("Los que empiezan con 'error_hacer_clicks_sunat_' o")
    print("'error_ingresar_credenciales_' son del LOGIN (lo mas probable dado el mensaje")
    print("de la alerta). Si la fecha/hora de alguno coincide con un FALLO de arriba,")
    print("comparte ese .html (o su nombre) para leerlo y confirmar que cambio en el portal.")


def main():
    db = SessionLocal()
    try:
        mostrar_canario(db)
        mostrar_consultas_recientes(db)
    finally:
        db.close()
    mostrar_evidencia_reciente()


if __name__ == "__main__":
    main()
