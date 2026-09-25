"""
Fase 5: verificacion de email por link de activacion. No bloquea el login
(el token de acceso ya sale de /auth/registro) -- estos tests cubren el
flujo de verificar el token y de pedir un reenvio.
"""
from datetime import datetime, timedelta, timezone

from app.models import Usuario


def _registrar(client, email="nuevo@example.com"):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": f"Tenant {email}", "email": email, "password": "ClaveSegura123!"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_usuario_nuevo_queda_sin_verificar_con_token_generado(client, db_session):
    _registrar(client, "sinverificar@example.com")
    usuario = db_session.query(Usuario).filter(Usuario.email == "sinverificar@example.com").first()
    assert usuario.email_verificado is False
    assert usuario.token_verificacion
    assert usuario.token_verificacion_expira is not None


def test_me_expone_email_verificado(client):
    headers = _registrar(client, "me@example.com")
    resp = client.get("/auth/me", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["email_verificado"] is False


def test_verificar_email_con_token_valido(client, db_session):
    _registrar(client, "valido@example.com")
    usuario = db_session.query(Usuario).filter(Usuario.email == "valido@example.com").first()
    token = usuario.token_verificacion

    resp = client.post(f"/auth/verificar-email/{token}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["verificado"] is True

    db_session.refresh(usuario)
    assert usuario.email_verificado is True
    assert usuario.token_verificacion is None
    assert usuario.token_verificacion_expira is None


def test_verificar_email_con_token_invalido_da_400(client):
    resp = client.post("/auth/verificar-email/token-que-no-existe")
    assert resp.status_code == 400


def test_verificar_email_con_token_vencido_da_400(client, db_session):
    _registrar(client, "vencido@example.com")
    usuario = db_session.query(Usuario).filter(Usuario.email == "vencido@example.com").first()
    usuario.token_verificacion_expira = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()

    resp = client.post(f"/auth/verificar-email/{usuario.token_verificacion}")
    assert resp.status_code == 400
    assert "vencio" in resp.json()["detail"].lower()


def test_reenviar_verificacion_regenera_el_token(client, db_session):
    headers = _registrar(client, "reenviar@example.com")
    usuario = db_session.query(Usuario).filter(Usuario.email == "reenviar@example.com").first()
    token_original = usuario.token_verificacion

    resp = client.post("/auth/reenviar-verificacion", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["enviado"] is True

    db_session.refresh(usuario)
    assert usuario.token_verificacion != token_original


def test_reenviar_verificacion_si_ya_esta_verificado_da_400(client, db_session):
    headers = _registrar(client, "yaverificado@example.com")
    usuario = db_session.query(Usuario).filter(Usuario.email == "yaverificado@example.com").first()
    usuario.email_verificado = True
    db_session.commit()

    resp = client.post("/auth/reenviar-verificacion", headers=headers)
    assert resp.status_code == 400
