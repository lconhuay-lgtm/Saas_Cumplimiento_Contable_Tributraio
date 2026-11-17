"""Boton "Activar todas" de la Liquidacion en vivo (datos ficticios)."""
from app.models import Empresa, LiquidacionEmpresa, LiquidacionEvento
from tests.test_rbac_miembro import _armar_tenant_con_miembro, _crear_empresa


def test_activar_todas(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)
    admin, miembro = ctx["headers_admin"], ctx["headers_miembro"]
    asignada, ajena = ctx["empresa_asignada_id"], ctx["empresa_ajena_id"]
    client.patch(f"/empresas/{ajena}", json={"activo": True}, headers=admin)
    de_baja = _crear_empresa(client, admin, "20333333333")
    client.patch(f"/empresas/{de_baja}", json={"activo": True}, headers=admin)
    db_session.get(Empresa, de_baja).estado_contribuyente = "BAJA DE OFICIO"
    db_session.commit()
    client.post(f"/liquidacion/empresas/{asignada}/activar", json={"activa": True}, headers=admin)
    url = "/liquidacion/empresas/activar-todas"

    assert client.post(url, headers=miembro).status_code == 403
    lista = {e["empresa_id"]: e for e in client.get("/liquidacion/empresas", headers=admin).json()["empresas"]}
    assert (lista[ajena]["activa_en_sunat"], lista[de_baja]["activa_en_sunat"]) == (True, False)

    r = client.post(url, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json() == {"activadas": 1, "ya_activas": 1, "saltadas": 1}
    db_session.expire_all()
    activas = {c.empresa_id for c in db_session.query(LiquidacionEmpresa).filter(LiquidacionEmpresa.activa.is_(True))}
    assert activas == {asignada, ajena}
    assert db_session.query(LiquidacionEvento).filter(
        LiquidacionEvento.empresa_id == ajena, LiquidacionEvento.accion == "activada").count() == 1

    # Pulsarlo de nuevo no cambia nada.
    assert client.post(url, headers=admin).json() == {"activadas": 0, "ya_activas": 2, "saltadas": 1}
