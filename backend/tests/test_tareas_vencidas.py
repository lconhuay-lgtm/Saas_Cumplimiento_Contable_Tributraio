"""
Fase 3: deteccion de tareas vencidas (pendientes con fecha ya pasada) --
filtro dedicado en /tareas, conteo en el panel "Avance de Cumplimiento" y
en el resumen del Dashboard.
"""
from datetime import datetime, timedelta, timezone

from app.models import TareaObligacion


def _registrar(client, email="admin@example.com"):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": "Estudio Vencidas", "email": email, "password": "ClaveSegura123!"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _crear_empresa(client, headers, ruc):
    return client.post(
        "/empresas",
        json={
            "ruc": ruc, "razon_social": f"Empresa {ruc}", "usuario_sol": "x", "clave_sol": "x",
            "obligacion_igv_renta": False,
        },
        headers=headers,
    ).json()["id"]


def _crear_tarea(db_session, empresa_id, *, dias_offset, estado="pendiente", tipo="otro", periodo=None):
    hoy = datetime.now(timezone.utc)
    tarea = TareaObligacion(
        empresa_id=empresa_id,
        titulo=f"Tarea {tipo}",
        tipo=tipo,
        periodo=periodo or f"{hoy.year:04d}-{hoy.month:02d}",
        fecha_vencimiento=hoy + timedelta(days=dias_offset),
        estado=estado,
        prioridad="media",
    )
    db_session.add(tarea)
    db_session.commit()
    return tarea


def test_filtro_vencida_solo_trae_pendientes_con_fecha_pasada(client, db_session):
    headers = _registrar(client)
    empresa_id = _crear_empresa(client, headers, "20211111111")

    _crear_tarea(db_session, empresa_id, dias_offset=-3, estado="pendiente")  # vencida
    _crear_tarea(db_session, empresa_id, dias_offset=5, estado="pendiente")  # futura, no vencida
    _crear_tarea(db_session, empresa_id, dias_offset=-3, estado="completado")  # vencida pero completada -> no cuenta

    tareas = client.get("/tareas?estado=vencida", headers=headers).json()
    assert len(tareas) == 1
    assert tareas[0]["estado"] == "pendiente"


def test_avance_cumplimiento_cuenta_vencidas_por_tipo(client, db_session):
    headers = _registrar(client)
    empresa_id = _crear_empresa(client, headers, "20222222222")
    hoy = datetime.now(timezone.utc)
    periodo_actual = f"{hoy.year:04d}-{hoy.month:02d}"

    _crear_tarea(db_session, empresa_id, dias_offset=-2, tipo="planilla", periodo=periodo_actual)
    _crear_tarea(db_session, empresa_id, dias_offset=10, tipo="planilla", periodo=periodo_actual)

    avance = client.get(f"/tareas/avance-cumplimiento?periodo={periodo_actual}", headers=headers).json()
    fila_planilla = next(p for p in avance["por_tipo"] if p["tipo"] == "Planilla")
    assert fila_planilla["total"] == 2
    assert fila_planilla["vencidas"] == 1
    assert avance["total"]["vencidas"] == 1


def test_dashboard_resumen_incluye_tareas_vencidas(client, db_session):
    headers = _registrar(client)
    empresa_id = _crear_empresa(client, headers, "20233333333")

    _crear_tarea(db_session, empresa_id, dias_offset=-1)
    _crear_tarea(db_session, empresa_id, dias_offset=-5)
    _crear_tarea(db_session, empresa_id, dias_offset=5)  # no vencida

    resumen = client.get("/dashboard/resumen", headers=headers).json()
    assert resumen["tareas_vencidas"] == 2
