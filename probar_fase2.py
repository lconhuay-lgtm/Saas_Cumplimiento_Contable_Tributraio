#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Prueba end-to-end de la Fase 2 (tablero + historial + chequeo nocturno +
resumen por correo). Se apoya en la empresa real ya usada en Fase 1
(credenciales leidas del Excel, nunca impresas).

Dos partes:
  A. Rapida y deterministica: CRUD nuevo (pendientes, marcar leido, marcar
     todos, pausar/reactivar empresa) usando mensajes de prueba insertados
     directo en la base (sin depender de SUNAT ni de limites de tiempo).
  B. Lenta pero real: dispara el chequeo nocturno manualmente (mismo camino
     que corre solo de madrugada) contra la empresa real, espera el
     resultado real de SUNAT, y despues el correo de resumen -- prueba que
     TODO el circuito nuevo de Fase 2 funciona de punta a punta.
"""
import subprocess
import sys
import time

import requests
import pandas as pd

BASE_URL = "http://localhost:8000"
EXCEL_PATH = r"J:\Automatiza_Sunat\Datos_Auto_SOL\Claves_Soltest.xls"
RUC_PRUEBA = "20494056934"  # MISKY SONCO SAC -- la misma empresa que en Fase 1
EMAIL_PRUEBA = "fase2@buzonsaas-dev.pe"
PASSWORD_PRUEBA = "ClaveSegura123!"


def paso(nombre):
    print(f"\n{'=' * 60}\n{nombre}\n{'=' * 60}")


def leer_credenciales_reales(ruc):
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


def registrar_o_iniciar_sesion():
    r = requests.post(f"{BASE_URL}/auth/registro", json={
        "nombre_tenant": "Estudio Fase 2",
        "email": EMAIL_PRUEBA,
        "password": PASSWORD_PRUEBA,
    })
    if r.status_code == 201:
        return r.json()["access_token"]
    if r.status_code == 409:
        r2 = requests.post(f"{BASE_URL}/auth/login", json={"email": EMAIL_PRUEBA, "password": PASSWORD_PRUEBA})
        if r2.status_code != 200:
            sys.exit(f"ERROR en login (tenant ya existia): {r2.status_code} {r2.text}")
        return r2.json()["access_token"]
    sys.exit(f"ERROR en registro: {r.status_code} {r.text}")


def crear_o_reutilizar_empresa(headers, datos):
    r = requests.post(f"{BASE_URL}/empresas", json=datos, headers=headers)
    if r.status_code == 201:
        return r.json()
    if r.status_code == 409:
        r2 = requests.get(f"{BASE_URL}/empresas", headers=headers)
        for e in r2.json():
            if e["ruc"] == datos["ruc"]:
                return e
    sys.exit(f"ERROR al crear/reutilizar empresa: {r.status_code} {r.text}")


def pendientes_de(headers, empresa_id):
    r = requests.get(f"{BASE_URL}/empresas", headers=headers)
    for e in r.json():
        if e["id"] == empresa_id:
            return e["pendientes"], e
    sys.exit("ERROR: la empresa desaparecio de /empresas")


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

    paso("2. Registrando (o reutilizando) tenant de prueba de Fase 2")
    token = registrar_o_iniciar_sesion()
    headers = {"Authorization": f"Bearer {token}"}
    print("Sesion OK")

    paso(f"3. Leyendo credenciales reales del Excel para RUC {RUC_PRUEBA} (no se imprimen)")
    datos_empresa = leer_credenciales_reales(RUC_PRUEBA)
    print(f"RUC: {datos_empresa['ruc']} - {datos_empresa['razon_social']} (usuario y clave OK, ocultos)")

    paso("4. Creando (o reutilizando) la empresa en la plataforma")
    empresa = crear_o_reutilizar_empresa(headers, datos_empresa)
    empresa_id = empresa["id"]
    print("Empresa:", empresa["ruc"], "-", empresa["razon_social"], "- id:", empresa_id)

    # ---------------- PARTE A: CRUD nuevo, rapido y deterministico ----------------

    paso("5A. Sembrando 2 mensajes de prueba directo en la base (sin pasar por SUNAT)")
    pendientes_antes, _ = pendientes_de(headers, empresa_id)
    resultado = subprocess.run(
        ["docker-compose", "exec", "-T", "backend", "python", "_sembrar_prueba_fase2.py", empresa_id],
        capture_output=True, text=True,
    )
    print(resultado.stdout.strip())
    if resultado.returncode != 0:
        sys.exit(f"ERROR sembrando datos de prueba: {resultado.stderr}")

    pendientes_despues, _ = pendientes_de(headers, empresa_id)
    print(f"Pendientes antes: {pendientes_antes} -> despues de sembrar: {pendientes_despues}")
    if pendientes_despues != pendientes_antes + 2:
        sys.exit("FALLO: el conteo de 'pendientes' no subio en 2 como se esperaba")
    print("OK: conteo de pendientes correcto")

    paso("6A. Marcando todos los mensajes de la empresa como leidos")
    r = requests.post(f"{BASE_URL}/empresas/{empresa_id}/mensajes/marcar-leidos", headers=headers)
    if r.status_code != 200:
        sys.exit(f"ERROR al marcar leidos: {r.status_code} {r.text}")
    print("Actualizados:", r.json()["actualizados"])

    pendientes_final, _ = pendientes_de(headers, empresa_id)
    if pendientes_final != 0:
        sys.exit(f"FALLO: pendientes deberia ser 0 despues de marcar todos leidos, salio {pendientes_final}")
    print("OK: pendientes en 0 tras marcar todos como leidos")

    paso("7A. Probando pausar / reactivar la empresa")
    r = requests.patch(f"{BASE_URL}/empresas/{empresa_id}", json={"activo": False}, headers=headers)
    if r.status_code != 200 or r.json()["activo"] is not False:
        sys.exit(f"FALLO al pausar la empresa: {r.status_code} {r.text}")
    r = requests.patch(f"{BASE_URL}/empresas/{empresa_id}", json={"activo": True}, headers=headers)
    if r.status_code != 200 or r.json()["activo"] is not True:
        sys.exit(f"FALLO al reactivar la empresa: {r.status_code} {r.text}")
    print("OK: pausar/reactivar funciona")

    # ---------------- PARTE B: chequeo nocturno real contra SUNAT ----------------

    paso("5B. Disparando el chequeo nocturno manualmente (entra a SUNAT de verdad)")
    r = requests.post(f"{BASE_URL}/admin/chequeo-nocturno", headers=headers)
    if r.status_code != 200:
        sys.exit(f"ERROR al disparar el chequeo nocturno: {r.status_code} {r.text}")
    resumen_chequeo = r.json()
    print("Respuesta:", resumen_chequeo)
    if resumen_chequeo["empresas_encoladas"] < 1:
        sys.exit("FALLO: el chequeo nocturno no encolo ninguna empresa (revisa que la empresa este activa)")

    paso("6B. Esperando el job que genero el chequeo nocturno para esta empresa (puede tardar 30-90s)")
    job = None
    for intento in range(40):
        r = requests.get(f"{BASE_URL}/empresas/{empresa_id}/jobs", headers=headers)
        jobs = r.json()
        candidato = jobs[0] if jobs else None
        if candidato and candidato["estado"] in ("completado", "error"):
            job = candidato
            break
        print(f"  [{intento+1}] estado: {candidato['estado'] if candidato else 'sin job todavia'}")
        time.sleep(5)
    if job is None:
        sys.exit("ERROR: el job del chequeo nocturno nunca termino (revisa 'docker-compose logs worker')")

    print("\nResultado final del job:", job)
    if job["estado"] == "error":
        sys.exit(f"\nFALLO: el chequeo nocturno fallo al consultar SUNAT: {job['error']}")

    paso("7B. Enviando (en modo prueba) el correo de resumen diario")
    r = requests.post(f"{BASE_URL}/admin/enviar-resumenes", headers=headers)
    if r.status_code != 200:
        sys.exit(f"ERROR al enviar resumenes: {r.status_code} {r.text}")
    resumen_correo = r.json()
    print("Respuesta:", resumen_correo)
    if job["mensajes_nuevos"] > 0 and resumen_correo["correos_enviados"] < 1:
        sys.exit("FALLO: hubo mensajes nuevos pero no se genero ningun correo de resumen")
    if job["mensajes_nuevos"] == 0:
        print("(No hubo mensajes nuevos en esta consulta real, asi que no se esperaba correo por esta parte -- normal si SUNAT no tiene notificaciones nuevas ahora mismo.)")

    print("\n" + "=" * 60)
    print("TODO OK -- Fase 2 funcionando de punta a punta:")
    print(f"  - CRUD nuevo (pendientes, marcar leido, pausar/reactivar): OK")
    print(f"  - Chequeo nocturno manual: {resumen_chequeo['empresas_encoladas']} empresa(s) encoladas")
    print(f"  - Consulta real a SUNAT via chequeo nocturno: {job['mensajes_nuevos']} mensaje(s) nuevo(s)")
    print(f"  - Resumen diario: {resumen_correo['correos_enviados']} correo(s) generado(s)")
    print("Revisa la carpeta sunat_data\\emails_dev\\ para ver los correos de prueba generados.")
    print("Abre http://localhost:3000 en el navegador para ver el tablero.")
    print("=" * 60)


if __name__ == "__main__":
    main()
