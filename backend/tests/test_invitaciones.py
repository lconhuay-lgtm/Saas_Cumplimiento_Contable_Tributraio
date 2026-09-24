"""
Invitar un usuario adicional al MISMO tenant (backend/app/routers/
invitaciones.py) -- la puerta de entrada que faltaba para clientes con mas
de un usuario.
"""
from app.models import Usuario, InvitacionUsuario


def _registrar(client, email, nombre_tenant):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": nombre_tenant, "email": email, "password": "ClaveSegura123!"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_crear_invitacion_y_aceptarla_crea_usuario_en_el_mismo_tenant(client, db_session):
    headers = _registrar(client, "admin@example.com", "Estudio Uno")
    admin = db_session.query(Usuario).filter(Usuario.email == "admin@example.com").first()

    resp = client.post("/invitaciones", json={"email": "asistente@example.com"}, headers=headers)
    assert resp.status_code == 201, resp.text
    invitacion = resp.json()
    assert invitacion["invitado_por_email"] == "admin@example.com"
    assert "/invitacion/" in invitacion["link"]

    token = invitacion["link"].rsplit("/", 1)[-1]

    info = client.get(f"/invitaciones/{token}/info")
    assert info.status_code == 200
    assert info.json() == {"valido": True, "motivo_invalido": None, "tenant_nombre": "Estudio Uno", "email": "asistente@example.com"}

    aceptar = client.post(f"/invitaciones/{token}/aceptar", json={"password": "OtraClaveSegura123!"})
    assert aceptar.status_code == 200, aceptar.text
    assert "access_token" in aceptar.json()

    nuevo = db_session.query(Usuario).filter(Usuario.email == "asistente@example.com").first()
    assert nuevo is not None
    assert nuevo.tenant_id == admin.tenant_id, "el usuario invitado debe quedar en el MISMO tenant, no uno nuevo"
    assert nuevo.rol == "miembro"


def test_no_se_puede_invitar_un_email_que_ya_es_usuario(client):
    headers = _registrar(client, "admin2@example.com", "Estudio Dos")
    resp = client.post("/invitaciones", json={"email": "admin2@example.com"}, headers=headers)
    assert resp.status_code == 409


def test_no_se_puede_duplicar_invitacion_pendiente(client):
    headers = _registrar(client, "admin3@example.com", "Estudio Tres")
    client.post("/invitaciones", json={"email": "repetido@example.com"}, headers=headers)
    resp = client.post("/invitaciones", json={"email": "repetido@example.com"}, headers=headers)
    assert resp.status_code == 409


def test_token_invalido_devuelve_no_valido(client):
    info = client.get("/invitaciones/token-que-no-existe/info")
    assert info.json()["valido"] is False

    resp = client.post("/invitaciones/token-que-no-existe/aceptar", json={"password": "ClaveSegura123!"})
    assert resp.status_code == 400


def test_invitacion_cancelada_no_se_puede_aceptar(client, db_session):
    headers = _registrar(client, "admin4@example.com", "Estudio Cuatro")
    invitacion = client.post("/invitaciones", json={"email": "cancelado@example.com"}, headers=headers).json()
    token = invitacion["link"].rsplit("/", 1)[-1]

    client.delete(f"/invitaciones/{invitacion['id']}", headers=headers)

    resp = client.post(f"/invitaciones/{token}/aceptar", json={"password": "ClaveSegura123!"})
    assert resp.status_code == 400
    assert "cancelada" in resp.json()["detail"].lower()


def test_invitacion_no_se_puede_usar_dos_veces(client):
    headers = _registrar(client, "admin5@example.com", "Estudio Cinco")
    invitacion = client.post("/invitaciones", json={"email": "una-vez@example.com"}, headers=headers).json()
    token = invitacion["link"].rsplit("/", 1)[-1]

    primera = client.post(f"/invitaciones/{token}/aceptar", json={"password": "ClaveSegura123!"})
    assert primera.status_code == 200

    segunda = client.post(f"/invitaciones/{token}/aceptar", json={"password": "OtraClave123!"})
    assert segunda.status_code == 400
    assert "usada" in segunda.json()["detail"].lower()


def test_listar_invitaciones_solo_del_propio_tenant(client):
    headers_a = _registrar(client, "tenanta@example.com", "Tenant A Inv")
    headers_b = _registrar(client, "tenantb@example.com", "Tenant B Inv")

    client.post("/invitaciones", json={"email": "para-a@example.com"}, headers=headers_a)
    client.post("/invitaciones", json={"email": "para-b@example.com"}, headers=headers_b)

    lista_a = client.get("/invitaciones", headers=headers_a).json()
    assert {i["email"] for i in lista_a} == {"para-a@example.com"}
