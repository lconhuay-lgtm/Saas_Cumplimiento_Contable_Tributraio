#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Prueba end-to-end del visor de PDF: fuerza que 2 mensajes ya conocidos de
la empresa real (MISKY SONCO SAC) vuelvan a aparecer como "nuevos", dispara
una consulta real a SUNAT (que ahora tambien intenta descargar sus
documentos), y verifica que el PDF quedo guardado y se puede leer via la
API igual que lo haria el visor del tablero.
"""
import subprocess
import sys
import time

import requests

BASE_URL = "http://localhost:8000"
RUC_PRUEBA = "20494056934"  # MISKY SONCO SAC
EMAIL_PRUEBA = "fase2@buzonsaas-dev.pe"  # el mismo tenant de prueba de Fase 2
PASSWORD_PRUEBA = "ClaveSegura123!"


def paso(nombre):
    print(f"\n{'=' * 60}\n{nombre}\n{'=' * 60}")


def iniciar_sesion():
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": EMAIL_PRUEBA, "password": PASSWORD_PRUEBA})
    if r.status_code != 200:
        sys.exit(
            f"ERROR en login: {r.status_code} {r.text}\n"
            "(Este script reutiliza el tenant de prueba de Fase 2 -- corre probar_fase2.bat primero si nunca se creo.)"
        )
    return r.json()["access_token"]


def main():
    paso("1. Esperando a que la API responda")
    for _ in range(20):
        try:
            if requests.get(f"{BASE_URL}/health", timeout=3).status_code == 200:
                print("API arriba")
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(2)
    else:
        sys.exit("ERROR: la API nunca respondio")

    paso("2. Iniciando sesion con el tenant de prueba")
    token = iniciar_sesion()
    headers = {"Authorization": f"Bearer {token}"}
    print("Sesion OK")

    paso(f"3. Buscando la empresa {RUC_PRUEBA}")
    r = requests.get(f"{BASE_URL}/empresas", headers=headers)
    empresa = next((e for e in r.json() if e["ruc"] == RUC_PRUEBA), None)
    if not empresa:
        sys.exit(f"No se encontro la empresa {RUC_PRUEBA} en este tenant. Corre probar_fase2.bat primero.")
    empresa_id = empresa["id"]
    print(f"Empresa: {empresa['razon_social']} - {empresa['total_mensajes']} mensaje(s) guardados")

    paso("4. Forzando que 2 mensajes ya conocidos vuelvan a aparecer como nuevos")
    resultado = subprocess.run(
        ["docker-compose", "exec", "-T", "backend", "python", "_forzar_mensajes_nuevos_prueba.py", empresa_id, "2"],
        capture_output=True, text=True,
    )
    print(resultado.stdout.strip())
    if resultado.returncode != 0:
        sys.exit(f"ERROR forzando mensajes de prueba: {resultado.stderr}")

    paso("5. Disparando una consulta real a SUNAT (ahora tambien descarga documentos)")
    r = requests.post(f"{BASE_URL}/empresas/{empresa_id}/consultar", headers=headers)
    if r.status_code != 202:
        sys.exit(f"ERROR al encolar: {r.status_code} {r.text}")
    job = r.json()
    print("Job encolado:", job["id"])

    paso("6. Esperando el resultado (puede tardar 1-3 minutos: login + navegacion + descargar 2 PDFs)")
    for intento in range(50):
        r = requests.get(f"{BASE_URL}/jobs/{job['id']}", headers=headers)
        job = r.json()
        print(f"  [{intento+1}] estado: {job['estado']}")
        if job["estado"] in ("completado", "error"):
            break
        time.sleep(5)
    else:
        sys.exit("ERROR: el job nunca termino (revisa 'docker-compose logs worker')")

    if job["estado"] == "error":
        sys.exit(f"\nFALLO: {job['error']}")

    print(f"\nResultado: {job['mensajes_nuevos']} mensaje(s) nuevo(s) procesados")

    paso("7. Verificando cuales de los mensajes nuevos tienen PDF disponible")
    r = requests.get(f"{BASE_URL}/empresas/{empresa_id}/mensajes", headers=headers)
    mensajes = r.json()
    recientes = sorted(mensajes, key=lambda m: m["descubierto_en"], reverse=True)[: job["mensajes_nuevos"] or 2]

    con_pdf = [m for m in recientes if m["tiene_documento"]]
    sin_pdf = [m for m in recientes if not m["tiene_documento"]]

    print(f"Con documento descargado: {len(con_pdf)}")
    for m in con_pdf:
        print(f"  - {m['asunto']}")
    if sin_pdf:
        print(f"Sin documento (revisar 'docker-compose logs worker' si esto es inesperado): {len(sin_pdf)}")
        for m in sin_pdf:
            print(f"  - {m['asunto']}")

    if not con_pdf:
        sys.exit(
            "\nFALLO: ningun mensaje quedo con documento descargado. "
            "Revisa docker-compose logs worker para ver en que punto fallo la descarga."
        )

    paso("8. Descargando uno de los PDFs por la API (lo mismo que hace el visor del tablero)")
    primero = con_pdf[0]
    r = requests.get(f"{BASE_URL}/empresas/{empresa_id}/mensajes/{primero['id']}/documento", headers=headers)
    if r.status_code != 200:
        sys.exit(f"FALLO: no se pudo leer el documento via API: {r.status_code} {r.text}")
    if r.headers.get("content-type") != "application/pdf" or not r.content.startswith(b"%PDF"):
        sys.exit("FALLO: la respuesta no parece ser un PDF valido")
    print(f"OK: PDF valido, {len(r.content)} bytes, content-type application/pdf")

    print("\n" + "=" * 60)
    print(f"TODO OK -- visor de PDF funcionando de punta a punta: {len(con_pdf)}/{len(recientes)} documento(s) descargados y verificados.")
    print("Abre http://localhost:3000 -> Empresas -> MISKY SONCO SAC y haz clic en 'Ver PDF' en un mensaje reciente.")
    print("=" * 60)


if __name__ == "__main__":
    main()
