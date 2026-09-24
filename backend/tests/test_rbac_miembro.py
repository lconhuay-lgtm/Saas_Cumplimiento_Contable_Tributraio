"""
RBAC dentro de un tenant (app/acceso.py + app/deps.py:get_admin_actual):
un "miembro" solo ve las empresas que tiene asignadas (y por extension sus
tareas/mensajes/jobs), no puede reasignar carteras, y no puede entrar a
Salud del sistema ni a Mi equipo -- eso queda solo para el "admin" (quien
se registro primero en el tenant, o a quien se le suba el rol a mano).
"""
from app.models import Usuario
from app.security import hash_password


def _registrar(client, email, nombre_tenant):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": nombre_tenant, "email": email, "password": "ClaveSegura123!"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _login(client, email):
    resp = client.post("/auth/login", json={"email": email, "password": "ClaveSegura123!"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _crear_miembro(db_session, tenant_id, email):
    """Simula lo que deja /invitaciones/{token}/aceptar: un Usuario nuevo con rol=miembro en el MISMO tenant."""
    usuario = Usuario(tenant_id=tenant_id, email=email, password_hash=hash_password("ClaveSegura123!"), rol="miembro")
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


def _armar_tenant_con_miembro(client, db_session):
    """Un admin con 2 empresas, una asignada a un miembro y otra no -- el fixture que reusan casi todos los tests de aca abajo."""
    token_admin = _registrar(client, "admin@example.com", "Estudio RBAC")
    headers_admin = {"Authorization": f"Bearer {token_admin}"}
    admin = db_session.query(Usuario).filter(Usuario.email == "admin@example.com").first()
    miembro = _crear_miembro(db_session, admin.tenant_id, "miembro@example.com")

    empresa_asignada_id = _crear_empresa(client, headers_admin, "20111111111")
    empresa_ajena_id = _crear_empresa(client, headers_admin, "20222222222")
    client.patch(
        f"/empresas/{empresa_asignada_id}",
        json={"activo": True, "asignado_a_usuario_id": miembro.id},
        headers=headers_admin,
    )

    token_miembro = _login(client, "miembro@example.com")
    headers_miembro = {"Authorization": f"Bearer {token_miembro}"}
    return {
        "headers_admin": headers_admin,
        "headers_miembro": headers_miembro,
        "miembro": miembro,
        "empresa_asignada_id": empresa_asignada_id,
        "empresa_ajena_id": empresa_ajena_id,
    }


def test_admin_ve_todas_las_empresas_miembro_solo_las_asignadas(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)

    ids_admin = {e["id"] for e in client.get("/empresas", headers=ctx["headers_admin"]).json()}
    assert ids_admin == {ctx["empresa_asignada_id"], ctx["empresa_ajena_id"]}

    ids_miembro = {e["id"] for e in client.get("/empresas", headers=ctx["headers_miembro"]).json()}
    assert ids_miembro == {ctx["empresa_asignada_id"]}


def test_miembro_no_puede_ver_detalle_de_empresa_ajena(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)

    resp_propia = client.get(f"/empresas/{ctx['empresa_asignada_id']}", headers=ctx["headers_miembro"])
    assert resp_propia.status_code == 200

    resp_ajena = client.get(f"/empresas/{ctx['empresa_ajena_id']}", headers=ctx["headers_miembro"])
    assert resp_ajena.status_code == 404


def test_miembro_no_puede_reasignar_cartera_admin_si(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)

    resp = client.patch(
        f"/empresas/{ctx['empresa_asignada_id']}",
        json={"activo": True, "asignado_a_usuario_id": None},
        headers=ctx["headers_miembro"],
    )
    assert resp.status_code == 403

    resp_admin = client.patch(
        f"/empresas/{ctx['empresa_asignada_id']}",
        json={"activo": True, "asignado_a_usuario_id": None},
        headers=ctx["headers_admin"],
    )
    assert resp_admin.status_code == 200
    assert resp_admin.json()["asignado_a_usuario_id"] is None


def test_miembro_solo_ve_tareas_de_sus_empresas(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)

    tarea_propia = client.post(
        "/tareas",
        json={"empresa_id": ctx["empresa_asignada_id"], "titulo": "Vencimiento propio", "fecha_vencimiento": "2026-10-15T00:00:00Z"},
        headers=ctx["headers_admin"],
    ).json()
    tarea_ajena = client.post(
        "/tareas",
        json={"empresa_id": ctx["empresa_ajena_id"], "titulo": "Vencimiento ajeno", "fecha_vencimiento": "2026-10-15T00:00:00Z"},
        headers=ctx["headers_admin"],
    ).json()

    tareas_admin = {t["id"] for t in client.get("/tareas", headers=ctx["headers_admin"]).json()}
    assert tareas_admin == {tarea_propia["id"], tarea_ajena["id"]}

    tareas_miembro = {t["id"] for t in client.get("/tareas", headers=ctx["headers_miembro"]).json()}
    assert tareas_miembro == {tarea_propia["id"]}

    resp = client.patch(f"/tareas/{tarea_ajena['id']}", json={"prioridad": "alta"}, headers=ctx["headers_miembro"])
    assert resp.status_code == 404


def test_miembro_no_puede_ver_salud_ni_equipo_admin_si(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)

    assert client.get("/admin/salud", headers=ctx["headers_miembro"]).status_code == 403
    assert client.get("/admin/errores-recientes", headers=ctx["headers_miembro"]).status_code == 403
    assert client.get("/admin/documentos-recientes", headers=ctx["headers_miembro"]).status_code == 403
    assert client.get("/invitaciones", headers=ctx["headers_miembro"]).status_code == 403
    assert client.post("/invitaciones", json={"email": "x@example.com"}, headers=ctx["headers_miembro"]).status_code == 403

    assert client.get("/admin/salud", headers=ctx["headers_admin"]).status_code == 200
    assert client.get("/invitaciones", headers=ctx["headers_admin"]).status_code == 200


def test_consultar_todas_solo_encola_empresas_visibles_del_miembro(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)

    resp = client.post("/empresas/consultar-todas", headers=ctx["headers_miembro"])
    assert resp.status_code == 200
    # El miembro solo tiene 1 empresa asignada, y ninguna tiene una
    # credencial real cargada por este flujo (se creo con usuario_sol/clave
    # de prueba, pero eso ya cuenta como "tiene credencial") -- lo que
    # importa es que no se haya intentado encolar la empresa ajena.
    assert resp.json()["empresas_encoladas"] + resp.json()["saltadas_sin_credencial"] == 1


def test_dashboard_resumen_solo_cuenta_empresas_visibles(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)

    resumen_admin = client.get("/dashboard/resumen", headers=ctx["headers_admin"]).json()
    assert resumen_admin["empresas_totales"] == 2

    resumen_miembro = client.get("/dashboard/resumen", headers=ctx["headers_miembro"]).json()
    assert resumen_miembro["empresas_totales"] == 1
