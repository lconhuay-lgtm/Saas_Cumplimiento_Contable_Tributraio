"""
Regresion del fix Fase R2 -- antes, /admin/chequeo-nocturno,
/admin/enviar-resumenes, /admin/canario/ejecutar y
/admin/reclasificar-mensajes solo exigian estar logueado, sin importar el
tenant. Cualquier estudio contable registrado podia disparar el chequeo
nocturno de TODOS los tenants.
"""
from app.models import Usuario

ENDPOINTS_OPERATIVOS = [
    "/admin/chequeo-nocturno",
    "/admin/enviar-resumenes",
    "/admin/canario/ejecutar",
    "/admin/reclasificar-mensajes",
]

ENDPOINTS_DE_LECTURA_PROPIA = [
    "/admin/salud",
    "/admin/errores-recientes",
    "/admin/documentos-recientes",
]


def _registrar(client, email):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": f"Tenant {email}", "email": email, "password": "ClaveSegura123!"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_endpoints_operativos_rechazan_usuario_normal(client):
    headers = _registrar(client, "normal@example.com")
    for ruta in ENDPOINTS_OPERATIVOS:
        resp = client.post(ruta, headers=headers)
        assert resp.status_code == 403, f"{ruta} deberia rechazar a un usuario sin es_staff_plataforma (dio {resp.status_code})"


def test_endpoints_operativos_aceptan_staff(client, db_session):
    headers = _registrar(client, "staff@example.com")

    usuario = db_session.query(Usuario).filter(Usuario.email == "staff@example.com").first()
    usuario.es_staff_plataforma = True
    db_session.commit()

    # Solo la accion segura e idempotente (no toca SUNAT ni manda correos,
    # igual que en la verificacion manual de la Fase R2).
    resp = client.post("/admin/reclasificar-mensajes", headers=headers)
    assert resp.status_code == 200, resp.text


def test_lectura_de_salud_sigue_abierta_a_cualquier_usuario(client):
    """
    Estos 3 endpoints NO deben exigir staff -- son datos del propio tenant,
    ya acotados por tenant_id en la Fase R1. Si alguna vez alguien los
    mueve por error a get_staff_actual, este test lo detecta.
    """
    headers = _registrar(client, "lectura@example.com")
    for ruta in ENDPOINTS_DE_LECTURA_PROPIA:
        resp = client.get(ruta, headers=headers)
        assert resp.status_code == 200, f"{ruta} no deberia exigir staff (dio {resp.status_code})"
