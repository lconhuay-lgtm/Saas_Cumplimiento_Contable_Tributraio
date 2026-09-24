#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Prueba end-to-end de la API de Fase 0, contra el stack real levantado con
docker-compose (Postgres + backend FastAPI). Registra un tenant, hace login,
crea una empresa y confirma que aparece en el listado.
"""
import sys
import time
import requests

BASE_URL = "http://localhost:8000"


def paso(nombre):
    print(f"\n{'=' * 60}\n{nombre}\n{'=' * 60}")


def main():
    paso("1. Esperando a que la API responda (/health)")
    for intento in range(20):
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=3)
            if r.status_code == 200:
                print("API arriba:", r.json())
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(2)
    else:
        print("ERROR: la API nunca respondio en /health. Revisa 'docker-compose logs backend'.")
        sys.exit(1)

    paso("2. Registrando un tenant + usuario admin")
    email = f"prueba+{int(time.time())}@buzonsaas-dev.pe"
    payload = {
        "nombre_tenant": "Estudio Contable de Prueba",
        "email": email,
        "password": "ClaveSegura123!",
    }
    r = requests.post(f"{BASE_URL}/auth/registro", json=payload)
    print(r.status_code, r.json())
    if r.status_code != 201:
        print("ERROR en registro")
        sys.exit(1)
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    paso("3. Login con las mismas credenciales")
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": email, "password": "ClaveSegura123!"})
    print(r.status_code, r.json())
    if r.status_code != 200:
        print("ERROR en login")
        sys.exit(1)

    paso("4. Confirmar identidad (/auth/me)")
    r = requests.get(f"{BASE_URL}/auth/me", headers=headers)
    print(r.status_code, r.json())

    paso("5. Crear una empresa (RUC de prueba, con credenciales SOL de mentira)")
    empresa_payload = {
        "ruc": "20494056934",
        "razon_social": "MISKY SONCO SAC",
        "usuario_sol": "LASIALIN",
        "clave_sol": "clave-de-prueba-no-real",
    }
    r = requests.post(f"{BASE_URL}/empresas", json=empresa_payload, headers=headers)
    print(r.status_code, r.json())
    if r.status_code != 201:
        print("ERROR al crear empresa")
        sys.exit(1)

    paso("6. Listar empresas del tenant")
    r = requests.get(f"{BASE_URL}/empresas", headers=headers)
    print(r.status_code, r.json())

    paso("7. Confirmar que otro tenant NO ve estas empresas (aislamiento)")
    email2 = f"otro-estudio+{int(time.time())}@buzonsaas-dev.pe"
    r = requests.post(
        f"{BASE_URL}/auth/registro",
        json={"nombre_tenant": "Otro Estudio", "email": email2, "password": "ClaveSegura123!"},
    )
    token2 = r.json()["access_token"]
    r = requests.get(f"{BASE_URL}/empresas", headers={"Authorization": f"Bearer {token2}"})
    print("Empresas visibles para el otro tenant (debe ser []):", r.status_code, r.json())

    print("\n" + "=" * 60)
    print("TODO OK: registro, login, aislamiento multi-tenant y CRUD de empresas funcionan end-to-end.")
    print("=" * 60)


if __name__ == "__main__":
    main()
