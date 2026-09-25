"""
Recurrencia flexible de obligaciones (Fase 2): filtro meses_activos sobre
EmpresaObligacion, mas los dos casos concretos que lo usan de entrada --
CTS (deposito semestral) e ITAN (recordatorio anual, o cuotas mensuales
via meses_activos si el contador lo configura asi).
"""
import io
from datetime import datetime, timezone

import pandas as pd

from app.models import CronogramaVencimiento


def _registrar(client, email="admin@example.com"):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": "Estudio Recurrencia", "email": email, "password": "ClaveSegura123!"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_cts_crea_obligacion_semestral_por_defecto(client):
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={
            "ruc": "20111111112", "razon_social": "Empresa CTS", "usuario_sol": "x", "clave_sol": "x",
            "obligacion_igv_renta": False, "obligacion_cts": True,
        },
        headers=headers,
    ).json()["id"]

    obligaciones = client.get(f"/empresas/{empresa_id}/obligaciones", headers=headers).json()
    assert len(obligaciones) == 1
    cts = obligaciones[0]
    assert cts["tipo"] == "cts"
    assert cts["regla_vencimiento"] == "dia_fijo_mes"
    assert cts["dia_fijo"] == 15
    assert cts["meses_activos"] == "5,11"


def test_cts_genera_tareas_solo_en_mayo_y_noviembre(client):
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={
            "ruc": "20222222223", "razon_social": "Empresa CTS2", "usuario_sol": "x", "clave_sol": "x",
            "obligacion_igv_renta": False, "obligacion_cts": True,
        },
        headers=headers,
    ).json()["id"]

    resp_enero = client.post("/tareas/generar?anio=2026&mes=1", headers=headers)
    assert resp_enero.json()["tareas_creadas"] == 0

    resp_mayo = client.post("/tareas/generar?anio=2026&mes=5", headers=headers)
    assert resp_mayo.json()["tareas_creadas"] == 1

    resp_noviembre = client.post("/tareas/generar?anio=2026&mes=11", headers=headers)
    assert resp_noviembre.json()["tareas_creadas"] == 1

    tareas = client.get(f"/tareas?empresa_id={empresa_id}", headers=headers).json()
    assert len(tareas) == 2
    fechas = sorted(t["fecha_vencimiento"][:10] for t in tareas)
    assert fechas == ["2026-05-15", "2026-11-15"]
    assert all(t["tipo"] == "cts" for t in tareas)


def test_itan_crea_recordatorio_anual_en_abril_por_defecto(client):
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={
            "ruc": "20333333334", "razon_social": "Empresa ITAN", "usuario_sol": "x", "clave_sol": "x",
            "obligacion_igv_renta": False, "obligacion_itan": True,
        },
        headers=headers,
    ).json()["id"]

    obligaciones = client.get(f"/empresas/{empresa_id}/obligaciones", headers=headers).json()
    assert len(obligaciones) == 1
    itan = obligaciones[0]
    assert itan["tipo"] == "itan"
    assert itan["regla_vencimiento"] == "dia_fijo_anual"
    assert itan["dia_fijo"] == 30
    assert itan["mes_fijo"] == 4

    resp_marzo = client.post("/tareas/generar?anio=2026&mes=3", headers=headers)
    assert resp_marzo.json()["tareas_creadas"] == 0

    resp_abril = client.post("/tareas/generar?anio=2026&mes=4", headers=headers)
    assert resp_abril.json()["tareas_creadas"] == 1

    tareas = client.get(f"/tareas?empresa_id={empresa_id}", headers=headers).json()
    assert len(tareas) == 1
    assert tareas[0]["fecha_vencimiento"].startswith("2026-04-30")


def test_meses_activos_filtra_cronograma_sunat_para_itan_en_cuotas(client, db_session):
    """Un contador puede reconfigurar ITAN a 9 cuotas mensuales (abril-diciembre)
    reusando el cronograma general en vez del recordatorio anual por defecto."""
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={
            "ruc": "20444444445", "razon_social": "Empresa ITAN Cuotas", "usuario_sol": "x", "clave_sol": "x",
            "obligacion_igv_renta": False,
        },
        headers=headers,
    ).json()["id"]

    resp = client.post(
        f"/empresas/{empresa_id}/obligaciones",
        json={
            "tipo": "itan", "nombre": "ITAN -- 9 cuotas",
            "regla_vencimiento": "cronograma_sunat", "meses_activos": "4,5,6,7,8,9,10,11,12",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    # RUC termina en 5 -> mismo grupo que en test_obligaciones_registro.py
    for periodo, dia in [("2026-03", 10), ("2026-04", 14)]:
        db_session.add(CronogramaVencimiento(
            periodo_tributario=periodo, grupo="4_5",
            fecha_vencimiento=datetime(2026, int(periodo[5:7]) + 1, dia, tzinfo=timezone.utc),
        ))
    db_session.commit()

    resp_marzo = client.post("/tareas/generar?anio=2026&mes=3", headers=headers)
    assert resp_marzo.json()["tareas_creadas"] == 0

    resp_abril = client.post("/tareas/generar?anio=2026&mes=4", headers=headers)
    assert resp_abril.json()["tareas_creadas"] == 1

    tareas = client.get(f"/tareas?empresa_id={empresa_id}", headers=headers).json()
    assert len(tareas) == 1
    assert tareas[0]["tipo"] == "itan"


def test_importar_excel_con_columnas_cts_itan(client):
    headers = _registrar(client)
    df = pd.DataFrame([
        {"RUC": "20555555556", "Usuario SOL": "u1", "Clave SOL": "c1", "CTS": "Si", "ITAN": "No"},
        {"RUC": "20666666667", "Usuario SOL": "u2", "Clave SOL": "c2", "CTS": "No", "ITAN": "Si"},
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
    e1 = next(e for e in empresas if e["ruc"] == "20555555556")
    e2 = next(e for e in empresas if e["ruc"] == "20666666667")

    obligaciones_1 = {o["tipo"] for o in client.get(f"/empresas/{e1['id']}/obligaciones", headers=headers).json()}
    obligaciones_2 = {o["tipo"] for o in client.get(f"/empresas/{e2['id']}/obligaciones", headers=headers).json()}
    assert obligaciones_1 == {"igv_renta", "cts"}
    assert obligaciones_2 == {"igv_renta", "itan"}
