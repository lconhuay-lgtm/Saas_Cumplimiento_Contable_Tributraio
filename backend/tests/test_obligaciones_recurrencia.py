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

    # Filtrado por esos dos periodos puntuales (no por toda la empresa) para
    # no depender de que mes es "hoy" quel corre el test -- la obligacion ya
    # se autogenera sola para el mes actual al crearse (ver mas abajo), asi
    # que si el test corriera justo en mayo o noviembre reales, la empresa
    # tendria una tarea de mas fuera de estos dos periodos.
    tareas_mayo = client.get(f"/tareas?empresa_id={empresa_id}&periodo=2026-05", headers=headers).json()
    tareas_noviembre = client.get(f"/tareas?empresa_id={empresa_id}&periodo=2026-11", headers=headers).json()
    assert len(tareas_mayo) == 1 and len(tareas_noviembre) == 1
    assert tareas_mayo[0]["fecha_vencimiento"].startswith("2026-05-15")
    assert tareas_noviembre[0]["fecha_vencimiento"].startswith("2026-11-15")
    assert tareas_mayo[0]["tipo"] == "cts" and tareas_noviembre[0]["tipo"] == "cts"


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

    tareas = client.get(f"/tareas?empresa_id={empresa_id}&periodo=2026-04", headers=headers).json()
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

    tareas = client.get(f"/tareas?empresa_id={empresa_id}&periodo=2026-04", headers=headers).json()
    assert len(tareas) == 1
    assert tareas[0]["tipo"] == "itan"


def test_prioridad_de_la_obligacion_se_copia_a_la_tarea_generada(client):
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={
            "ruc": "20121212121", "razon_social": "Empresa Prioridad", "usuario_sol": "x", "clave_sol": "x",
            "obligacion_igv_renta": False,
        },
        headers=headers,
    ).json()["id"]

    resp = client.post(
        f"/empresas/{empresa_id}/obligaciones",
        json={
            "tipo": "otro", "nombre": "Recordatorio urgente", "regla_vencimiento": "dia_fijo_mes",
            "dia_fijo": 10, "prioridad": "urgente",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["prioridad"] == "urgente"

    hoy = datetime.now(timezone.utc)
    periodo_actual = f"{hoy.year:04d}-{hoy.month:02d}"
    tareas = client.get(f"/tareas?empresa_id={empresa_id}&periodo={periodo_actual}", headers=headers).json()
    assert len(tareas) == 1
    assert tareas[0]["prioridad"] == "urgente"


def test_prioridad_por_defecto_de_obligacion_es_media(client):
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={"ruc": "20131313131", "razon_social": "Empresa Prioridad2", "usuario_sol": "x", "clave_sol": "x"},
        headers=headers,
    ).json()["id"]

    obligaciones = client.get(f"/empresas/{empresa_id}/obligaciones", headers=headers).json()
    assert obligaciones[0]["prioridad"] == "media"


def test_crear_obligacion_genera_tarea_del_mes_actual_sin_boton_manual(client):
    """Bug reportado: crear una obligacion dejaba la tarea del mes actual
    invisible en Tareas/Calendario hasta que alguien se acordara de apretar
    "Generar tareas del mes" aparte -- ahora se dispara sola al crearla."""
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={
            "ruc": "20777777778", "razon_social": "Empresa Auto", "usuario_sol": "x", "clave_sol": "x",
            "obligacion_igv_renta": False,
        },
        headers=headers,
    ).json()["id"]

    resp = client.post(
        f"/empresas/{empresa_id}/obligaciones",
        json={"tipo": "otro", "nombre": "Recordatorio mensual", "regla_vencimiento": "dia_fijo_mes", "dia_fijo": 10},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    hoy = datetime.now(timezone.utc)
    periodo_actual = f"{hoy.year:04d}-{hoy.month:02d}"
    # Sin llamar a /tareas/generar -- la tarea del mes actual ya debe existir.
    tareas = client.get(f"/tareas?empresa_id={empresa_id}&periodo={periodo_actual}", headers=headers).json()
    assert len(tareas) == 1
    assert tareas[0]["tipo"] == "otro"


def test_crear_empresa_con_obligacion_por_defecto_genera_tarea_sin_boton_manual(client, db_session):
    """Mismo bug, pero por el camino de _crear_obligaciones_por_defecto
    (alta manual de empresa) -- IGV-Renta debe generar su tarea del mes
    actual de una, sin que el usuario tenga que ir a Tareas a generarla."""
    headers = _registrar(client)
    hoy = datetime.now(timezone.utc)
    periodo_actual = f"{hoy.year:04d}-{hoy.month:02d}"

    # RUC termina en 5 -> grupo "4_5" (ver cronograma_sunat.grupo_para_empresa)
    db_session.add(CronogramaVencimiento(
        periodo_tributario=periodo_actual, grupo="4_5",
        fecha_vencimiento=hoy,
    ))
    db_session.commit()

    empresa_id = client.post(
        "/empresas",
        json={"ruc": "20999999995", "razon_social": "Empresa Auto3", "usuario_sol": "x", "clave_sol": "x"},
        headers=headers,
    ).json()["id"]

    tareas = client.get(f"/tareas?empresa_id={empresa_id}&periodo={periodo_actual}", headers=headers).json()
    assert len(tareas) == 1
    assert tareas[0]["tipo"] == "igv_renta"


def test_activar_obligacion_genera_tarea_del_mes_actual_sin_boton_manual(client):
    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={
            "ruc": "20101010101", "razon_social": "Empresa Auto4", "usuario_sol": "x", "clave_sol": "x",
            "obligacion_igv_renta": False,
        },
        headers=headers,
    ).json()["id"]

    obligacion_id = client.post(
        f"/empresas/{empresa_id}/obligaciones",
        json={
            "tipo": "otro", "nombre": "Recordatorio inactivo", "regla_vencimiento": "dia_fijo_mes",
            "dia_fijo": 20, "activa": False,
        },
        headers=headers,
    ).json()["id"]

    hoy = datetime.now(timezone.utc)
    periodo_actual = f"{hoy.year:04d}-{hoy.month:02d}"
    tareas_antes = client.get(f"/tareas?empresa_id={empresa_id}&periodo={periodo_actual}", headers=headers).json()
    assert tareas_antes == []

    resp = client.patch(f"/obligaciones/{obligacion_id}", json={"activa": True}, headers=headers)
    assert resp.status_code == 200, resp.text

    tareas_despues = client.get(f"/tareas?empresa_id={empresa_id}&periodo={periodo_actual}", headers=headers).json()
    assert len(tareas_despues) == 1


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
