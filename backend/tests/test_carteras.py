"""
Carteras: asignar una empresa a un usuario del tenant (backend/app/routers/
empresas.py PATCH + backend/app/routers/usuarios.py).
"""
from app.models import Usuario


def _registrar(client, email, nombre_tenant):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": nombre_tenant, "email": email, "password": "ClaveSegura123!"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _agregar_segundo_usuario_mismo_tenant(db_session, tenant_id, email):
    """No hay endpoint para invitar companeros -- se inserta directo, como
    haria una futura pantalla de 'invitar miembro al equipo'."""
    from app.security import hash_password

    usuario = Usuario(tenant_id=tenant_id, email=email, password_hash=hash_password("ClaveSegura123!"))
    db_session.add(usuario)
    db_session.commit()
    return usuario


def _crear_empresa(client, headers, ruc):
    resp = client.post(
        "/empresas",
        json={"ruc": ruc, "razon_social": f"Empresa {ruc}", "usuario_sol": "x", "clave_sol": "x"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_listar_usuarios_solo_del_propio_tenant(client, db_session):
    token_a = _registrar(client, "a@example.com", "Tenant A")
    _registrar(client, "otro@example.com", "Tenant Otro")  # tenant distinto

    usuario_a = db_session.query(Usuario).filter(Usuario.email == "a@example.com").first()
    _agregar_segundo_usuario_mismo_tenant(db_session, usuario_a.tenant_id, "companero@example.com")

    resp = client.get("/usuarios", headers={"Authorization": f"Bearer {token_a}"})
    emails = {u["email"] for u in resp.json()}
    assert emails == {"a@example.com", "companero@example.com"}
    assert "otro@example.com" not in emails


def test_asignar_desasignar_y_reasignar_empresa(client, db_session):
    token = _registrar(client, "duena@example.com", "Estudio Cartera")
    headers = {"Authorization": f"Bearer {token}"}
    usuario = db_session.query(Usuario).filter(Usuario.email == "duena@example.com").first()
    companero = _agregar_segundo_usuario_mismo_tenant(db_session, usuario.tenant_id, "asistente@example.com")

    empresa_id = _crear_empresa(client, headers, "20111111111")

    resp = client.patch(f"/empresas/{empresa_id}", json={"activo": True, "asignado_a_usuario_id": companero.id}, headers=headers)
    assert resp.json()["asignado_a_usuario_id"] == companero.id

    resp = client.patch(f"/empresas/{empresa_id}", json={"activo": True, "asignado_a_usuario_id": None}, headers=headers)
    assert resp.json()["asignado_a_usuario_id"] is None

    resp = client.patch(f"/empresas/{empresa_id}", json={"activo": True, "asignado_a_usuario_id": companero.id}, headers=headers)
    assert resp.json()["asignado_a_usuario_id"] == companero.id


def test_no_se_puede_asignar_a_usuario_de_otro_tenant(client, db_session):
    token = _registrar(client, "propio@example.com", "Estudio Propio")
    headers = {"Authorization": f"Bearer {token}"}
    empresa_id = _crear_empresa(client, headers, "20222222222")

    _registrar(client, "ajeno@example.com", "Estudio Ajeno")
    usuario_ajeno = db_session.query(Usuario).filter(Usuario.email == "ajeno@example.com").first()

    resp = client.patch(
        f"/empresas/{empresa_id}",
        json={"activo": True, "asignado_a_usuario_id": usuario_ajeno.id},
        headers=headers,
    )
    assert resp.status_code == 400


def test_omitir_el_campo_no_toca_una_asignacion_existente(client, db_session):
    token = _registrar(client, "duena2@example.com", "Estudio Cartera 2")
    headers = {"Authorization": f"Bearer {token}"}
    usuario = db_session.query(Usuario).filter(Usuario.email == "duena2@example.com").first()
    companero = _agregar_segundo_usuario_mismo_tenant(db_session, usuario.tenant_id, "asistente2@example.com")
    empresa_id = _crear_empresa(client, headers, "20333333333")

    client.patch(f"/empresas/{empresa_id}", json={"activo": True, "asignado_a_usuario_id": companero.id}, headers=headers)

    # Un PATCH que solo toca es_canario, sin mencionar asignado_a_usuario_id,
    # no debe desasignar la empresa por accidente.
    resp = client.patch(f"/empresas/{empresa_id}", json={"activo": True, "es_canario": True}, headers=headers)
    assert resp.json()["asignado_a_usuario_id"] == companero.id


def test_tarea_hereda_el_asignado_de_su_empresa(client, db_session):
    token = _registrar(client, "duena3@example.com", "Estudio Cartera 3")
    headers = {"Authorization": f"Bearer {token}"}
    usuario = db_session.query(Usuario).filter(Usuario.email == "duena3@example.com").first()
    companero = _agregar_segundo_usuario_mismo_tenant(db_session, usuario.tenant_id, "asistente3@example.com")
    empresa_id = _crear_empresa(client, headers, "20444444444")
    client.patch(f"/empresas/{empresa_id}", json={"activo": True, "asignado_a_usuario_id": companero.id}, headers=headers)

    tarea = client.post(
        "/tareas",
        json={"empresa_id": empresa_id, "titulo": "Vencimiento IGV", "fecha_vencimiento": "2026-10-15T00:00:00Z"},
        headers=headers,
    ).json()
    assert tarea["empresa_asignado_a_usuario_id"] == companero.id

    filtradas = client.get(f"/tareas?asignado_a_usuario_id={companero.id}", headers=headers).json()
    assert {t["id"] for t in filtradas} == {tarea["id"]}

    vacio = client.get(f"/tareas?asignado_a_usuario_id={usuario.id}", headers=headers).json()
    assert vacio == []
