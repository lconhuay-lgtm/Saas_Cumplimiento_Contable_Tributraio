"""Registro, login y /auth/me (backend/app/routers/auth.py)."""


def test_registro_crea_tenant_y_login_funciona(client):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": "Estudio Contable Test", "email": "contador@example.com", "password": "ClaveSegura123!"},
    )
    assert resp.status_code == 201
    assert "access_token" in resp.json()

    login = client.post("/auth/login", json={"email": "contador@example.com", "password": "ClaveSegura123!"})
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "contador@example.com"


def test_login_con_clave_incorrecta_devuelve_401(client):
    client.post(
        "/auth/registro",
        json={"nombre_tenant": "Otro Estudio", "email": "otro@example.com", "password": "ClaveCorrecta123!"},
    )
    resp = client.post("/auth/login", json={"email": "otro@example.com", "password": "ClaveIncorrecta"})
    assert resp.status_code == 401


def test_login_con_email_inexistente_devuelve_401(client):
    resp = client.post("/auth/login", json={"email": "no-existe@example.com", "password": "loquesea"})
    assert resp.status_code == 401


def test_registro_con_email_duplicado_falla(client):
    payload = {"nombre_tenant": "Estudio Duplicado", "email": "dup@example.com", "password": "ClaveSegura123!"}
    client.post("/auth/registro", json=payload)
    resp = client.post("/auth/registro", json=payload)
    assert resp.status_code == 409


def test_endpoint_protegido_sin_token_devuelve_401(client):
    resp = client.get("/auth/me")
    assert resp.status_code in (401, 403)  # HTTPBearer sin credenciales devuelve 403 en FastAPI
