#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Prueba end-to-end de la Fase 1: registra una empresa con credenciales SOL
REALES (leidas directamente del Excel de pruebas, nunca impresas ni
mostradas), encola una consulta en vivo, y espera el resultado del worker.

La clave SOL viaja del Excel -> este script -> la API (por localhost) ->
se cifra antes de guardarse. En ningun momento se imprime en pantalla.
"""
import sys
import time
import requests
import pandas as pd

BASE_URL = "http://localhost:8000"
EXCEL_PATH = r"J:\Automatiza_Sunat\Datos_Auto_SOL\Claves_Soltest.xls"
RUC_PRUEBA = "20494056934"  # MISKY SONCO SAC -- ya usado en pruebas anteriores de este proyecto


def paso(nombre):
    print(f"\n{'=' * 60}\n{nombre}\n{'=' * 60}")


def leer_credenciales_reales(ruc):
    """Lee usuario/clave SOL reales del Excel de pruebas, sin exponerlas."""
    df = pd.read_excel(EXCEL_PATH, sheet_name=0)
    columnas = {}
    for col in df.columns:
        if not isinstance(col, str):
            continue
        cl = col.lower()
        if "ruc" in cl:
            columnas["ruc"] = col
        elif "usuario" in cl or "user" in cl:
            columnas["usuario"] = col
        elif "clave" in cl or "password" in cl or "contraseña" in cl:
            columnas["clave"] = col
        elif "contribuyente" in cl or "razon" in cl:
            columnas["razon_social"] = col

    df[columnas["ruc"]] = df[columnas["ruc"]].astype(str).str.strip()
    fila = df[df[columnas["ruc"]] == ruc]
    if fila.empty:
        raise SystemExit(f"No se encontro el RUC {ruc} en el Excel")

    fila = fila.iloc[0]
    return {
        "ruc": ruc,
        "usuario_sol": str(fila[columnas["usuario"]]).strip(),
        "clave_sol": str(fila[columnas["clave"]]).strip(),
        "razon_social": str(fila[columnas.get("razon_social", columnas["ruc"])]).strip(),
    }


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

    paso("2. Registrando tenant de prueba")
    email = f"fase1+{int(time.time())}@buzonsaas-dev.pe"
    r = requests.post(f"{BASE_URL}/auth/registro", json={
        "nombre_tenant": "Estudio Fase 1",
        "email": email,
        "password": "ClaveSegura123!",
    })
    if r.status_code != 201:
        sys.exit(f"ERROR en registro: {r.status_code} {r.text}")
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    print("Tenant registrado OK")

    paso(f"3. Leyendo credenciales reales del Excel para RUC {RUC_PRUEBA} (no se imprimen)")
    empresa_datos = leer_credenciales_reales(RUC_PRUEBA)
    print(f"RUC: {empresa_datos['ruc']} - {empresa_datos['razon_social']} (usuario y clave OK, ocultos)")

    paso("4. Creando la empresa en la plataforma (la clave se cifra al guardarse)")
    r = requests.post(f"{BASE_URL}/empresas", json=empresa_datos, headers=headers)
    if r.status_code != 201:
        sys.exit(f"ERROR al crear empresa: {r.status_code} {r.text}")
    empresa_id = r.json()["id"]
    print("Empresa creada:", r.json()["ruc"], "-", r.json()["razon_social"])

    paso("5. Encolando consulta en vivo al buzon SOL (esto entra a SUNAT de verdad)")
    r = requests.post(f"{BASE_URL}/empresas/{empresa_id}/consultar", headers=headers)
    if r.status_code != 202:
        sys.exit(f"ERROR al encolar: {r.status_code} {r.text}")
    job = r.json()
    print("Job encolado:", job["id"], "- estado:", job["estado"])

    paso("6. Esperando a que el worker procese el job (puede tardar 30-90s)")
    job_id = job["id"]
    for intento in range(40):
        r = requests.get(f"{BASE_URL}/jobs/{job_id}", headers=headers)
        job = r.json()
        print(f"  [{intento+1}] estado: {job['estado']}")
        if job["estado"] in ("completado", "error"):
            break
        time.sleep(5)
    else:
        sys.exit("ERROR: el job nunca termino (revisa 'docker-compose logs worker')")

    print("\nResultado final del job:", job)

    if job["estado"] == "error":
        sys.exit(f"\nFALLO: {job['error']}")

    paso("7. Leyendo los mensajes guardados en la base de datos")
    r = requests.get(f"{BASE_URL}/empresas/{empresa_id}/mensajes", headers=headers)
    mensajes = r.json()
    print(f"Mensajes guardados: {len(mensajes)}")
    for m in mensajes[:5]:
        print(f"  - {m['fecha_publicacion']}: {m['asunto']}")

    print("\n" + "=" * 60)
    print(f"TODO OK -- Fase 1 funcionando de punta a punta: {job['mensajes_nuevos']} mensajes nuevos, "
          f"{len(mensajes)} guardados en total para {empresa_datos['razon_social']}.")
    print("=" * 60)


if __name__ == "__main__":
    main()
