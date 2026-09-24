"""
Crear una tarea a partir de una notificacion puntual del buzon
(TareaObligacion.mensaje_buzon_id) -- el usuario carga la fecha real, el
sistema nunca inventa un plazo legal.
"""
from datetime import datetime, timezone

from app.models import MensajeBuzon


def _registrar_con_empresa(client, email, ruc):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": f"Tenant {email}", "email": email, "password": "ClaveSegura123!"},
    )
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    empresa_id = client.post(
        "/empresas",
        json={"ruc": ruc, "razon_social": f"Empresa {ruc}", "usuario_sol": "x", "clave_sol": "x"},
        headers=headers,
    ).json()["id"]
    return headers, empresa_id


def _crear_mensaje(db_session, empresa_id, asunto="Esquela de prueba"):
    mensaje = MensajeBuzon(
        empresa_id=empresa_id,
        mensaje_externo_id="ext-001",
        fecha_publicacion=datetime.now(timezone.utc),
        asunto=asunto,
        leido=False,
    )
    db_session.add(mensaje)
    db_session.commit()
    return mensaje


def test_crear_tarea_desde_mensaje(client, db_session):
    headers, empresa_id = _registrar_con_empresa(client, "user1@example.com", "20111111111")
    mensaje = _crear_mensaje(db_session, empresa_id)

    resp = client.post(
        "/tareas",
        json={"empresa_id": empresa_id, "titulo": mensaje.asunto, "tipo": "notificacion", "mensaje_buzon_id": mensaje.id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["mensaje_buzon_id"] == mensaje.id
    assert resp.json()["fecha_vencimiento"] is None, "sin fecha explicita, no se debe inventar un plazo"


def test_no_se_puede_crear_dos_tareas_para_el_mismo_mensaje(client, db_session):
    headers, empresa_id = _registrar_con_empresa(client, "user2@example.com", "20222222222")
    mensaje = _crear_mensaje(db_session, empresa_id)

    payload = {"empresa_id": empresa_id, "titulo": mensaje.asunto, "mensaje_buzon_id": mensaje.id}
    primera = client.post("/tareas", json=payload, headers=headers)
    assert primera.status_code == 201

    segunda = client.post("/tareas", json=payload, headers=headers)
    assert segunda.status_code == 409


def test_mensaje_de_otra_empresa_no_se_puede_usar(client, db_session):
    headers, empresa_id = _registrar_con_empresa(client, "user3@example.com", "20333333333")
    _, otra_empresa_id = _registrar_con_empresa(client, "user4@example.com", "20444444444")
    mensaje_de_otra = _crear_mensaje(db_session, otra_empresa_id)

    resp = client.post(
        "/tareas",
        json={"empresa_id": empresa_id, "titulo": "x", "mensaje_buzon_id": mensaje_de_otra.id},
        headers=headers,
    )
    assert resp.status_code == 400


def test_filtrar_tareas_por_mensaje(client, db_session):
    headers, empresa_id = _registrar_con_empresa(client, "user5@example.com", "20555555555")
    mensaje = _crear_mensaje(db_session, empresa_id)
    client.post(
        "/tareas",
        json={"empresa_id": empresa_id, "titulo": mensaje.asunto, "mensaje_buzon_id": mensaje.id},
        headers=headers,
    )
    # Una tarea suelta, sin mensaje, no debe aparecer en el filtro.
    client.post("/tareas", json={"empresa_id": empresa_id, "titulo": "Tarea suelta"}, headers=headers)

    resp = client.get(f"/tareas?mensaje_buzon_id={mensaje.id}", headers=headers)
    tareas = resp.json()
    assert len(tareas) == 1
    assert tareas[0]["mensaje_buzon_id"] == mensaje.id
