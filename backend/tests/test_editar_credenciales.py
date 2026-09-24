"""PATCH /empresas/{id}/credenciales -- cambiar usuario/clave SOL guardados."""
from app.models import CredencialSol
from app.security import descifrar_clave_sol


def test_actualizar_credenciales_re_cifra_la_clave_nueva(client, db_session):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": "Estudio Credenciales", "email": "cred@example.com", "password": "ClaveSegura123!"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    empresa_id = client.post(
        "/empresas",
        json={"ruc": "20111111111", "razon_social": "Empresa X", "usuario_sol": "userviejo", "clave_sol": "claveVieja"},
        headers=headers,
    ).json()["id"]

    resp = client.patch(
        f"/empresas/{empresa_id}/credenciales",
        json={"usuario_sol": "usernuevo", "clave_sol": "claveNueva123"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    credencial = db_session.query(CredencialSol).filter(CredencialSol.empresa_id == empresa_id).first()
    assert credencial.usuario_sol == "usernuevo"
    assert descifrar_clave_sol(credencial.clave_cifrada, credencial.dek_cifrada) == "claveNueva123"


def test_no_se_puede_editar_credenciales_de_empresa_de_otro_tenant(client):
    headers_a = {
        "Authorization": f"Bearer {client.post('/auth/registro', json={'nombre_tenant': 'T1', 'email': 'a@example.com', 'password': 'ClaveSegura123!'}).json()['access_token']}"
    }
    headers_b = {
        "Authorization": f"Bearer {client.post('/auth/registro', json={'nombre_tenant': 'T2', 'email': 'b@example.com', 'password': 'ClaveSegura123!'}).json()['access_token']}"
    }
    empresa_id = client.post(
        "/empresas",
        json={"ruc": "20222222222", "razon_social": "Empresa Y", "usuario_sol": "x", "clave_sol": "x"},
        headers=headers_a,
    ).json()["id"]

    resp = client.patch(
        f"/empresas/{empresa_id}/credenciales",
        json={"usuario_sol": "hackeo", "clave_sol": "hackeo123"},
        headers=headers_b,
    )
    assert resp.status_code == 404
