"""Liquidacion en vivo, Etapa 1: activacion, permisos, credenciales de la API del SIRE y prueba de conexion."""
from datetime import date

import app.routers.liquidacion as liquidacion
from app.models import (
    DeclaracionSunat, LiquidacionCalculo, LiquidacionComprobante, LiquidacionConciliacion, LiquidacionCuentaControl,
    LiquidacionDeclaracion, LiquidacionEmpresa, LiquidacionEvento, LiquidacionLectura, LiquidacionRetencionPercepcion, Usuario,
)
from app.sire_api import ErrorApiSire
from tests.test_rbac_miembro import _armar_tenant_con_miembro

API = {"client_id": "cliente-123456789", "client_secret": "secreto-abcdefgh"}


def _activar(client, ctx, empresa_id, activa=True, headers="headers_admin"):
    return client.post(f"/liquidacion/empresas/{empresa_id}/activar", json={"activa": activa}, headers=ctx[headers])


def test_solo_el_admin_activa_y_se_cuentan_las_activas(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)
    assert _activar(client, ctx, ctx["empresa_asignada_id"], headers="headers_miembro").status_code == 403

    r = _activar(client, ctx, ctx["empresa_asignada_id"])
    assert r.status_code == 200 and r.json()["activa"] is True and r.json()["estado"] == "falta_api"

    lista = client.get("/liquidacion/empresas", headers=ctx["headers_admin"]).json()
    assert (lista["activas"], lista["incluidas"], lista["es_admin"]) == (1, 15, True)
    assert {e["empresa_id"] for e in lista["empresas"]} == {ctx["empresa_asignada_id"], ctx["empresa_ajena_id"]}

    # El miembro solo ve su empresa asignada.
    lista_miembro = client.get("/liquidacion/empresas", headers=ctx["headers_miembro"]).json()
    assert [e["empresa_id"] for e in lista_miembro["empresas"]] == [ctx["empresa_asignada_id"]]


def test_regimen_sugerido_por_el_tributo_de_renta(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)
    db_session.add_all([
        DeclaracionSunat(empresa_id=ctx["empresa_asignada_id"], periodo="2026-05", formulario="1662", num_orden="1",
                         cod_tributo="3031", fecha_presentacion=date(2026, 6, 10)),
        DeclaracionSunat(empresa_id=ctx["empresa_asignada_id"], periodo="2026-08", formulario="1662", num_orden="2",
                         cod_tributo="3121", fecha_presentacion=date(2026, 9, 10)),
    ])
    db_session.commit()
    r = _activar(client, ctx, ctx["empresa_asignada_id"]).json()
    assert (r["regimen"], r["regimen_origen"], r["regimen_sugerido"]) == ("mype", "pagos", "mype")

    r = client.put(f"/empresas/{ctx['empresa_asignada_id']}/liquidacion/regimen", json={"regimen": "agrario"}, headers=ctx["headers_miembro"])
    assert r.status_code == 200 and (r.json()["regimen"], r.json()["regimen_origen"]) == ("agrario", "manual")
    assert client.put(f"/empresas/{ctx['empresa_asignada_id']}/liquidacion/regimen", json={"regimen": "otro"}, headers=ctx["headers_miembro"]).status_code == 400


def test_solo_el_responsable_guarda_las_credenciales(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)
    url = f"/empresas/{ctx['empresa_asignada_id']}/liquidacion/api"
    assert client.put(url, json=API, headers=ctx["headers_miembro"]).status_code == 400  # todavia no activada

    _activar(client, ctx, ctx["empresa_asignada_id"])
    assert client.put(url, json=API, headers=ctx["headers_admin"]).status_code == 403  # el admin no es el responsable
    r = client.put(url, json=API, headers=ctx["headers_miembro"])
    assert r.status_code == 200 and r.json()["estado"] == "sin_probar"

    config = db_session.get(LiquidacionEmpresa, ctx["empresa_asignada_id"])
    db_session.refresh(config)
    assert config.api_client_id == API["client_id"]
    assert API["client_secret"].encode() not in config.api_secret_cifrado

    detalle = client.get(f"/empresas/{ctx['empresa_asignada_id']}/liquidacion", headers=ctx["headers_miembro"]).json()
    assert detalle["api_client_id"] == "••••6789" and detalle["puede_editar_api"] is True
    assert [e["accion"] for e in detalle["eventos"]] == ["api_guardada", "activada"]

    # Empresa sin responsable: nadie puede guardar credenciales hasta asignarlo.
    _activar(client, ctx, ctx["empresa_ajena_id"])
    r = client.put(f"/empresas/{ctx['empresa_ajena_id']}/liquidacion/api", json=API, headers=ctx["headers_admin"])
    assert r.status_code == 400 and "responsable" in r.json()["detail"]


def test_probar_conexion(client, db_session, monkeypatch):
    ctx = _armar_tenant_con_miembro(client, db_session)
    _activar(client, ctx, ctx["empresa_asignada_id"])
    client.put(f"/empresas/{ctx['empresa_asignada_id']}/liquidacion/api", json=API, headers=ctx["headers_miembro"])
    url = f"/empresas/{ctx['empresa_asignada_id']}/liquidacion/probar"

    recibido = {}

    def conexion_ok(client_id, client_secret, ruc, usuario_sol, clave_sol):
        recibido.update(client_id=client_id, client_secret=client_secret, ruc=ruc)
        return 12

    monkeypatch.setattr(liquidacion, "probar_conexion", conexion_ok)
    r = client.post(url, headers=ctx["headers_admin"]).json()
    assert (r["estado"], r["sire_periodos"]) == ("lista", 12)
    assert recibido == {"client_id": API["client_id"], "client_secret": API["client_secret"], "ruc": "20111111111"}

    monkeypatch.setattr(liquidacion, "probar_conexion", lambda *a: 0)
    assert client.post(url, headers=ctx["headers_miembro"]).json()["estado"] == "no_afiliada"

    def conexion_falla(*a):
        raise ErrorApiSire("El ID o la clave de la API no son válidos.")

    monkeypatch.setattr(liquidacion, "probar_conexion", conexion_falla)
    r = client.post(url, headers=ctx["headers_miembro"]).json()
    assert (r["estado"], r["api_mensaje"]) == ("api_error", "El ID o la clave de la API no son válidos.")


def test_miembro_no_ve_empresa_ajena(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)
    assert client.get(f"/empresas/{ctx['empresa_ajena_id']}/liquidacion", headers=ctx["headers_miembro"]).status_code == 404


def test_eliminar_empresa_borra_sus_datos_de_liquidacion(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)
    eid = ctx["empresa_asignada_id"]
    _activar(client, ctx, eid)
    db_session.add_all([
        LiquidacionLectura(empresa_id=eid, fuente="sire"),
        LiquidacionDeclaracion(empresa_id=eid, periodo="2026-09", num_orden="1212191089", casillas={"184": 55213.0}),
        LiquidacionComprobante(empresa_id=eid, periodo="2026-09", libro="RVIE", fuente="propuesta", car_sunat="CAR1", datos={}),
        LiquidacionRetencionPercepcion(empresa_id=eid, tipo="retencion", origen="comprobante", documento="R001-1", periodo="2026-09"),
        LiquidacionCuentaControl(empresa_id=eid, periodo="2026-09", tipo="retencion"),
        LiquidacionCalculo(empresa_id=eid, periodo="2026-10", fecha=date(2026, 10, 28), casillas={}, fuentes={}),
        LiquidacionConciliacion(empresa_id=eid, periodo="2026-09", num_orden="1212191089", casilla="184"),
    ])
    db_session.commit()

    assert client.delete(f"/empresas/{eid}", headers=ctx["headers_admin"]).status_code == 204
    db_session.expire_all()
    for modelo in (LiquidacionEmpresa, LiquidacionEvento, LiquidacionLectura, LiquidacionDeclaracion, LiquidacionComprobante,
                   LiquidacionRetencionPercepcion, LiquidacionCuentaControl, LiquidacionCalculo, LiquidacionConciliacion):
        assert db_session.query(modelo).filter_by(empresa_id=eid).count() == 0, modelo.__tablename__
