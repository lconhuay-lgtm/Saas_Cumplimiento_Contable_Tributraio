"""
Fase 5: "panel maestro" -- GET/PUT /admin/configuracion, solo para staff de
la plataforma (mismo criterio de aislamiento que test_staff_only.py).
"""
from app.models import Usuario, ConfiguracionSistema


def _registrar(client, email):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": f"Tenant {email}", "email": email, "password": "ClaveSegura123!"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _hacer_staff(db_session, email):
    usuario = db_session.query(Usuario).filter(Usuario.email == email).first()
    usuario.es_staff_plataforma = True
    db_session.commit()


def test_usuario_normal_no_puede_ver_ni_editar_configuracion(client):
    headers = _registrar(client, "normal@example.com")
    assert client.get("/admin/configuracion", headers=headers).status_code == 403
    assert client.put("/admin/configuracion", headers=headers, json={"concurrencia_maxima": 5}).status_code == 403


def test_staff_obtiene_los_valores_por_defecto(client, db_session):
    headers = _registrar(client, "staff1@example.com")
    _hacer_staff(db_session, "staff1@example.com")

    resp = client.get("/admin/configuracion", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["limite_mensajes_por_consulta"] == 20
    assert data["espaciado_seg_entre_consultas"] == 45
    assert data["concurrencia_maxima"] == 3
    assert data["segundos_entre_consultas_mismo_ruc"] == 60

    # get-or-create: la fila unica ya debe existir en la base tras el GET.
    assert db_session.query(ConfiguracionSistema).filter(ConfiguracionSistema.id == "global").first() is not None


def test_staff_puede_editar_solo_algunos_campos(client, db_session):
    headers = _registrar(client, "staff2@example.com")
    _hacer_staff(db_session, "staff2@example.com")

    resp = client.put("/admin/configuracion", headers=headers, json={"concurrencia_maxima": 7})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["concurrencia_maxima"] == 7
    # Los campos que no se mandaron no deben cambiar.
    assert data["espaciado_seg_entre_consultas"] == 45

    config = db_session.query(ConfiguracionSistema).filter(ConfiguracionSistema.id == "global").first()
    assert config.concurrencia_maxima == 7
    assert config.actualizado_por_usuario_id is not None


def test_put_rechaza_valores_fuera_de_rango(client, db_session):
    headers = _registrar(client, "staff3@example.com")
    _hacer_staff(db_session, "staff3@example.com")

    resp = client.put("/admin/configuracion", headers=headers, json={"concurrencia_maxima": 0})
    assert resp.status_code == 422
