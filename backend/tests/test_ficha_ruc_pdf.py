"""PDF de la Ficha RUC: se sirve la ultima generada y el navegador no debe guardar copias viejas (datos ficticios)."""
import app.almacenamiento as almacenamiento
from app.models import Empresa
from tests.test_rbac_miembro import _armar_tenant_con_miembro


def test_pdf_de_la_ficha_ruc_sin_cache(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(almacenamiento, "LOCAL_BASE_DIR", str(tmp_path))
    ctx = _armar_tenant_con_miembro(client, db_session)
    emp = ctx["empresa_asignada_id"]
    url = f"/empresas/{emp}/ficha-ruc/pdf"

    assert client.get(url, headers=ctx["headers_admin"]).status_code == 404  # todavia no se genero

    empresa = db_session.get(Empresa, emp)
    empresa.ficha_ruc_pdf_ref = almacenamiento.guardar_documento_bytes(b"%PDF vieja", emp, "ficha-ruc")
    db_session.commit()
    # Una ficha nueva reemplaza el archivo en la misma referencia.
    assert almacenamiento.guardar_documento_bytes(b"%PDF nueva", emp, "ficha-ruc") == empresa.ficha_ruc_pdf_ref

    r = client.get(url, headers=ctx["headers_admin"])
    assert r.status_code == 200
    assert r.content == b"%PDF nueva"
    assert r.headers["cache-control"] == "no-store"
