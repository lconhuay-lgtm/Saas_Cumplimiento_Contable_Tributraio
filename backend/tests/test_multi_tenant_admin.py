"""
Regresion del fix Fase R1 -- este es el bug real que se encontro:
/admin/salud y /admin/errores-recientes mezclaban datos de TODOS los
tenants, sin filtrar por tenant_id. Estos tests deben fallar si alguna vez
se revierte ese fix (por ejemplo, si alguien "simplifica" una de las 4
queries afectadas en admin.py y se olvida del join con Empresa).
"""
from datetime import datetime, timedelta, timezone

from app.models import ConsultaJob


def _crear_tenant_con_empresa(client, sufijo, ruc):
    registro = client.post(
        "/auth/registro",
        json={
            "nombre_tenant": f"Tenant {sufijo}",
            "email": f"user{sufijo}@example.com",
            "password": "ClaveSegura123!",
        },
    )
    assert registro.status_code == 201, registro.text
    token = registro.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    empresa_resp = client.post(
        "/empresas",
        json={
            "ruc": ruc,
            "razon_social": f"Empresa Secreta {sufijo}",
            "usuario_sol": "x",
            "clave_sol": "x",
        },
        headers=headers,
    )
    assert empresa_resp.status_code == 201, empresa_resp.text
    return headers, empresa_resp.json()["id"]


def _insertar_job_error(db_session, empresa_id, mensaje_error):
    job = ConsultaJob(
        empresa_id=empresa_id,
        estado="error",
        iniciado_en=datetime.now(timezone.utc) - timedelta(seconds=10),
        finalizado_en=datetime.now(timezone.utc),
        mensajes_nuevos=0,
        error=mensaje_error,
    )
    db_session.add(job)
    db_session.commit()


def test_errores_recientes_no_filtra_entre_tenants(client, db_session):
    headers_a, empresa_a = _crear_tenant_con_empresa(client, "A", "20111111111")
    headers_b, empresa_b = _crear_tenant_con_empresa(client, "B", "20222222222")

    _insertar_job_error(db_session, empresa_a, "error tenant A")
    _insertar_job_error(db_session, empresa_b, "error tenant B")

    rucs_vistos_por_a = {
        item["empresa_ruc"] for item in client.get("/admin/errores-recientes", headers=headers_a).json()
    }
    assert rucs_vistos_por_a == {"20111111111"}, "Tenant A no deberia ver el error de Tenant B"

    rucs_vistos_por_b = {
        item["empresa_ruc"] for item in client.get("/admin/errores-recientes", headers=headers_b).json()
    }
    assert rucs_vistos_por_b == {"20222222222"}, "Tenant B no deberia ver el error de Tenant A"


def test_salud_no_agrega_consultas_de_otros_tenants(client, db_session):
    headers_a, empresa_a = _crear_tenant_con_empresa(client, "C", "20333333333")
    headers_b, empresa_b = _crear_tenant_con_empresa(client, "D", "20444444444")

    _insertar_job_error(db_session, empresa_a, "error")
    _insertar_job_error(db_session, empresa_b, "error")
    _insertar_job_error(db_session, empresa_b, "error")

    salud_a = client.get("/admin/salud?horas_atras=1", headers=headers_a).json()
    assert salud_a["consultas"]["total"] == 1, "Tenant A deberia ver solo SU propio job, no el agregado del sistema"

    salud_b = client.get("/admin/salud?horas_atras=1", headers=headers_b).json()
    assert salud_b["consultas"]["total"] == 2
