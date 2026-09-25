"""
Fase 4: obligacion SIRE (Atraso de Registros Electronicos) -- checkbox de
registro, regla_vencimiento="cronograma_sire" y que la tarea generada NO
se duplique con la del cronograma mensual (misma empresa/periodo, pero
son dos obligaciones y dos fechas distintas).
"""
from datetime import datetime, timezone

from app.models import CronogramaVencimiento


def _registrar(client, email="admin@example.com"):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": "Estudio SIRE", "email": email, "password": "ClaveSegura123!"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_checkbox_sire_crea_obligacion_con_regla_cronograma_sire(client):
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={
            "ruc": "20141414141", "razon_social": "Empresa SIRE", "usuario_sol": "x", "clave_sol": "x",
            "obligacion_igv_renta": False, "obligacion_sire": True,
        },
        headers=headers,
    ).json()["id"]

    obligaciones = client.get(f"/empresas/{empresa_id}/obligaciones", headers=headers).json()
    assert len(obligaciones) == 1
    assert obligaciones[0]["tipo"] == "sire"
    assert obligaciones[0]["regla_vencimiento"] == "cronograma_sire"


def test_sire_genera_tarea_con_su_propia_fecha_sin_chocar_con_mensual(client, db_session):
    """RUC termina en 4 -> grupo "4_5". Se siembra el cronograma mensual Y el
    SIRE del mismo periodo+grupo con fechas DISTINTAS -- generar_tareas_mes
    debe traer la fecha SIRE para la obligacion sire, no la mensual."""
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={
            "ruc": "20444444444", "razon_social": "Empresa SIRE2", "usuario_sol": "x", "clave_sol": "x",
            "obligacion_igv_renta": True, "obligacion_sire": True,
        },
        headers=headers,
    ).json()["id"]

    db_session.add(CronogramaVencimiento(
        periodo_tributario="2026-03", grupo="4_5", tipo="mensual",
        fecha_vencimiento=datetime(2026, 4, 14, tzinfo=timezone.utc),
    ))
    db_session.add(CronogramaVencimiento(
        periodo_tributario="2026-03", grupo="4_5", tipo="sire",
        fecha_vencimiento=datetime(2026, 4, 20, tzinfo=timezone.utc),
    ))
    db_session.commit()

    resp = client.post("/tareas/generar?anio=2026&mes=3", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["tareas_creadas"] == 2  # igv_renta + sire

    tareas = client.get(f"/tareas?empresa_id={empresa_id}&periodo=2026-03", headers=headers).json()
    assert len(tareas) == 2
    por_tipo = {t["tipo"]: t for t in tareas}
    assert por_tipo["igv_renta"]["fecha_vencimiento"].startswith("2026-04-14")
    assert por_tipo["sire"]["fecha_vencimiento"].startswith("2026-04-20")


def test_importar_excel_con_columna_sire(client):
    import io
    import pandas as pd

    headers = _registrar(client)
    df = pd.DataFrame([
        {"RUC": "20151515151", "Usuario SOL": "u1", "Clave SOL": "c1", "SIRE": "Si"},
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
    assert obligaciones == {"igv_renta", "sire"}
