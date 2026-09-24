#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Corre una vez despues de actualizar el codigo para que los mensajes que ya
estaban guardados (de antes de que existiera la clasificacion por tipo)
queden con su categoria calculada -- los mensajes nuevos ya se clasifican
solos a partir de ahora, esto es solo para "ponerse al dia" con lo viejo.
Seguro de correr mas de una vez.
"""
import sys
import requests

BASE_URL = "http://localhost:8000"
EMAIL_PRUEBA = "fase2@buzonsaas-dev.pe"
PASSWORD_PRUEBA = "ClaveSegura123!"

r = requests.post(f"{BASE_URL}/auth/login", json={"email": EMAIL_PRUEBA, "password": PASSWORD_PRUEBA})
if r.status_code != 200:
    sys.exit(f"ERROR en login: {r.status_code} {r.text}")
headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

r = requests.post(f"{BASE_URL}/admin/reclasificar-mensajes", headers=headers)
if r.status_code != 200:
    sys.exit(f"ERROR: {r.status_code} {r.text}")

resultado = r.json()
print(f"Mensajes revisados: {resultado['mensajes_revisados']}")
print(f"Mensajes reclasificados: {resultado['mensajes_actualizados']}")
