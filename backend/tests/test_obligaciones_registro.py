"""
Obligaciones seleccionables al registrar una empresa (manual y por Excel)
-- Fase 1 del plan de obligaciones inteligentes. IGV-Renta y PLAME deben
generar tareas automaticamente sin que el usuario configure nada despues.
"""
import io
from datetime import datetime, timezone

import pandas as pd

from app.models import CronogramaVencimiento


def _registrar(client, email="admin@example.com"):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": "Estudio Obligaciones", "email": email, "password": "ClaveSegura123!"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_crear_empresa_manual_activa_igv_renta_por_defecto(client):
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={"ruc": "20111111111", "razon_social": "Empresa X", "usuario_sol": "x", "clave_sol": "x"},
        headers=headers,
    ).json()["id"]

    obligaciones = client.get(f"/empresas/{empresa_id}/obligaciones", headers=headers).json()
    assert len(obligaciones) == 1
    assert obligaciones[0]["tipo"] == "igv_renta"
    assert obligaciones[0]["regla_vencimiento"] == "cronograma_sunat"
    assert obligaciones[0]["activa"] is True


def test_crear_empresa_con_plame_crea_planilla_y_afp(client):
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={
            "ruc": "20222222222", "razon_social": "Empresa Y", "usuario_sol": "x", "clave_sol": "x",
            "obligacion_plame": True, "obligacion_sbs": True,
        },
        headers=headers,
    ).json()["id"]

    obligaciones = client.get(f"/empresas/{empresa_id}/obligaciones", headers=headers).json()
    tipos = {o["tipo"] for o in obligaciones}
    assert tipos == {"igv_renta", "planilla", "afp", "sbs"}
    sbs = next(o for o in obligaciones if o["tipo"] == "sbs")
    assert sbs["regla_vencimiento"] == "manual"


def test_crear_empresa_sin_ninguna_obligacion(client):
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={
            "ruc": "20333333333", "razon_social": "Empresa Z", "usuario_sol": "x", "clave_sol": "x",
            "obligacion_igv_renta": False,
        },
        headers=headers,
    ).json()["id"]

    obligaciones = client.get(f"/empresas/{empresa_id}/obligaciones", headers=headers).json()
    assert obligaciones == []


def test_igv_renta_genera_tarea_automatica_sin_configuracion_manual(client, db_session):
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={"ruc": "20444444444", "razon_social": "Empresa Cronograma", "usuario_sol": "x", "clave_sol": "x"},
        headers=headers,
    ).json()["id"]

    # RUC termina en 4 -> grupo "4_5" (ver cronograma_sunat.grupo_para_empresa)
    db_session.add(CronogramaVencimiento(
        periodo_tributario="2026-03", grupo="4_5",
        fecha_vencimiento=datetime(2026, 4, 14, tzinfo=timezone.utc),
    ))
    db_session.commit()

    resp = client.post("/tareas/generar?anio=2026&mes=3", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["tareas_creadas"] == 1

    tareas = client.get(f"/tareas?empresa_id={empresa_id}&periodo=2026-03", headers=headers).json()
    assert len(tareas) == 1
    assert tareas[0]["tipo"] == "igv_renta"
    assert tareas[0]["fecha_vencimiento"].startswith("2026-04-14")


def test_dia_fijo_anual_solo_genera_tarea_en_su_mes(client):
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={
            "ruc": "20555555555", "razon_social": "Empresa Anual", "usuario_sol": "x", "clave_sol": "x",
            "obligacion_igv_renta": False,
        },
        headers=headers,
    ).json()["id"]

    resp = client.post(
        f"/empresas/{empresa_id}/obligaciones",
        json={
            "tipo": "otro", "nombre": "Declaracion Jurada Anual",
            "regla_vencimiento": "dia_fijo_anual", "dia_fijo": 15, "mes_fijo": 2,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    # Enero: no le toca (mes_fijo=2)
    resp_enero = client.post("/tareas/generar?anio=2026&mes=1", headers=headers)
    assert resp_enero.json()["tareas_creadas"] == 0

    # Febrero: si le toca, con fecha 15/02
    resp_febrero = client.post("/tareas/generar?anio=2026&mes=2", headers=headers)
    assert resp_febrero.json()["tareas_creadas"] == 1

    # Filtrado por periodo (no por toda la empresa): la obligacion ya se
    # autogenera sola para el mes actual al crearse (ver
    # test_obligaciones_recurrencia.py), asi que si este test corriera
    # justo en un febrero real, la empresa tendria ademas la tarea de ese
    # periodo real, distinto de "2026-02".
    tareas = client.get(f"/tareas?empresa_id={empresa_id}&periodo=2026-02", headers=headers).json()
    assert len(tareas) == 1
    assert tareas[0]["fecha_vencimiento"].startswith("2026-02-15")


def test_importar_excel_con_columnas_de_obligaciones(client):
    headers = _registrar(client)
    df = pd.DataFrame([
        {"RUC": "20666666666", "Usuario SOL": "u1", "Clave SOL": "c1", "IGV-Renta": "Si", "PLAME": "No", "SBS": "Si"},
        {"RUC": "20777777777", "Usuario SOL": "u2", "Clave SOL": "c2", "IGV-Renta": "No", "PLAME": "Si", "SBS": "No"},
    ])
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)

    resp = client.post(
        "/empresas/importar",
        files={"archivo": ("empresas.xlsx", buffer, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["creadas"] == 2

    empresas = client.get("/empresas", headers=headers).json()
    e1 = next(e for e in empresas if e["ruc"] == "20666666666")
    e2 = next(e for e in empresas if e["ruc"] == "20777777777")

    obligaciones_1 = {o["tipo"] for o in client.get(f"/empresas/{e1['id']}/obligaciones", headers=headers).json()}
    obligaciones_2 = {o["tipo"] for o in client.get(f"/empresas/{e2['id']}/obligaciones", headers=headers).json()}
    assert obligaciones_1 == {"igv_renta", "sbs"}
    assert obligaciones_2 == {"planilla", "afp"}


def test_importar_excel_sin_columnas_de_obligaciones_usa_default(client):
    """Un Excel viejo, sin las columnas nuevas, sigue funcionando igual que antes (IGV-Renta por defecto)."""
    headers = _registrar(client)
    df = pd.DataFrame([
        {"RUC": "20888888888", "Usuario SOL": "u3", "Clave SOL": "c3"},
    ])
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)

    resp = client.post(
        "/empresas/importar",
        files={"archivo": ("empresas.xlsx", buffer, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["creadas"] == 1

    empresa = client.get("/empresas", headers=headers).json()[0]
    obligaciones = {o["tipo"] for o in client.get(f"/empresas/{empresa['id']}/obligaciones", headers=headers).json()}
    assert obligaciones == {"igv_renta"}
