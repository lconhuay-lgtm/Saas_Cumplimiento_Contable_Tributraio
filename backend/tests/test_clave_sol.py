"""
Clave SOL para la PLAME (app/routers/clave_sol.py): PIN de 4 digitos por
usuario, ver RUC/usuario/clave de una empresa visible, bloqueo tras PIN
errados y registro de cada vista.
"""
from datetime import datetime, timedelta, timezone

from app.models import Usuario, VistaClaveSol
from tests.test_rbac_miembro import _armar_tenant_con_miembro

CLAVE_CUENTA = "ClaveSegura123!"


def _crear_pin(client, headers, pin="2580"):
    return client.post("/auth/pin", json={"pin": pin, "password": CLAVE_CUENTA}, headers=headers)


def test_crear_pin_pide_la_contrasena_y_rechaza_pins_obvios(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)
    h = ctx["headers_miembro"]
    assert client.get("/auth/pin", headers=h).json() == {"tiene_pin": False, "bloqueado_hasta": None}
    assert client.get("/auth/me", headers=h).json()["tiene_pin"] is False

    assert client.post("/auth/pin", json={"pin": "2580", "password": "otra"}, headers=h).status_code == 400
    for malo in ("1111", "1234", "4321", "12a4", "123", "12345"):
        assert _crear_pin(client, h, malo).status_code == 422, malo

    assert _crear_pin(client, h).status_code == 200
    assert client.get("/auth/pin", headers=h).json()["tiene_pin"] is True
    assert client.get("/auth/me", headers=h).json()["tiene_pin"] is True
    miembro = db_session.query(Usuario).filter(Usuario.email == "miembro@example.com").one()
    assert miembro.pin_hash and "2580" not in miembro.pin_hash


def test_ver_clave_sol_con_pin_solo_de_empresas_visibles(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)
    h = ctx["headers_miembro"]
    url = f"/empresas/{ctx['empresa_asignada_id']}/clave-sol/ver"

    assert client.post(url, json={"pin": "2580"}, headers=h).status_code == 409  # todavia sin PIN
    _crear_pin(client, h)

    r = client.post(url, json={"pin": "2580"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    datos = r.json()
    assert (datos["ruc"], datos["usuario_sol"], datos["clave_sol"]) == ("20111111111", "x", "x")
    assert datos["visible_seg"] > 0

    # La empresa no asignada no existe para el miembro; el admin si la ve.
    ajena = f"/empresas/{ctx['empresa_ajena_id']}/clave-sol/ver"
    assert client.post(ajena, json={"pin": "2580"}, headers=h).status_code == 404
    _crear_pin(client, ctx["headers_admin"], "7391")
    assert client.post(ajena, json={"pin": "7391"}, headers=ctx["headers_admin"]).status_code == 200

    vistas = db_session.query(VistaClaveSol).all()
    assert len(vistas) == 2 and {v.motivo for v in vistas} == {"plame"}


def test_pin_errado_bloquea_y_no_cierra_la_sesion(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)
    h = ctx["headers_miembro"]
    url = f"/empresas/{ctx['empresa_asignada_id']}/clave-sol/ver"
    _crear_pin(client, h)

    for restantes in (4, 3, 2, 1):
        r = client.post(url, json={"pin": "0000"}, headers=h)
        assert r.status_code == 400 and f"{restantes} intento" in r.json()["detail"]
    r = client.post(url, json={"pin": "0000"}, headers=h)
    assert r.status_code == 423
    # Bloqueado: ni el PIN correcto sirve.
    assert client.post(url, json={"pin": "2580"}, headers=h).status_code == 423
    assert client.get("/auth/pin", headers=h).json()["bloqueado_hasta"] is not None
    assert db_session.query(VistaClaveSol).count() == 0

    # Pasado el bloqueo vuelve a funcionar; cambiar el PIN con la contrasena tambien lo libera.
    miembro = db_session.query(Usuario).filter(Usuario.email == "miembro@example.com").one()
    miembro.pin_bloqueado_hasta = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert client.post(url, json={"pin": "2580"}, headers=h).status_code == 200
    miembro.pin_bloqueado_hasta = datetime.now(timezone.utc) + timedelta(minutes=10)
    db_session.commit()
    assert _crear_pin(client, h, "8642").status_code == 200
    assert client.post(url, json={"pin": "8642"}, headers=h).status_code == 200
