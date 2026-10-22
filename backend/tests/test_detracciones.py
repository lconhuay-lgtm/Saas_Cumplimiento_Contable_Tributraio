"""
Cumplimiento > Detracciones: "Consulta de Pago de Detracciones" de SUNAT
(tramos de 30 dias, normalizacion, historial acumulado y busqueda por API).
"""
from datetime import date, datetime, timedelta, timezone

from adapter import normalizar_detraccion, tramos_fechas
from app.jobs import aplicar_lectura_detracciones
from app.models import ConsultaDetraccionesJob, DetraccionPago


def _crudo(constancia, proveedor_ruc="20101281702", monto=666.0, fecha="2026-03-19", periodo="202603"):
    # Misma forma que devuelve el servicio de SUNAT (leido de Bascat el 21/10/2026, datos inventados).
    return {
        "num_pres": 7756129409, "cod_usuario_sol": "USUARIO1", "des_prov": "PROVEEDOR S.A.C.",
        "cod_tipcomprobante": "01", "num_ruc_proveedor": proveedor_ruc, "per_tributario": periodo,
        "fec_pago_desc": fecha, "num_npd": " ", "des_adq": "CLIENTE S A C", "num_constancia": constancia,
        "tip_bien": "037", "tip_operacion": "01", "num_doc_adq": "20505018509", "mto_deposito_desc": f"{monto:.2f}",
        "num_cuenta": "00021008141", "mto_deposito": monto, "num_comprobante": "00005847", "fec_pago": 1773954449000,
        "tip_doc_adq": "06", "num_serie": "F001", "origen_desc": "WEB SUNAT", "cod_tipcta": "1",
    }


def test_tramos_de_30_dias():
    tramos = tramos_fechas(date(2026, 1, 1), date(2026, 3, 31))
    assert tramos == [
        (date(2026, 1, 1), date(2026, 1, 30)),
        (date(2026, 1, 31), date(2026, 3, 1)),
        (date(2026, 3, 2), date(2026, 3, 31)),
    ]
    assert all((fin - ini).days <= 29 for ini, fin in tramos)
    assert tramos_fechas(date(2026, 3, 5), date(2026, 3, 5)) == [(date(2026, 3, 5), date(2026, 3, 5))]


def test_normalizar_detraccion():
    d = normalizar_detraccion(_crudo("300485576"), "pagosIndividuales")
    assert d["num_constancia"] == "300485576"
    assert d["periodo"] == "2026-03" and d["fecha_pago"] == "2026-03-19"
    assert d["monto"] == 666.0 and d["num_pago"] == "" and d["tipo_bien"] == "037"
    assert (d["serie"], d["numero"], d["tipo_cuenta"]) == ("F001", "00005847", "1")
    # Sin monto numerico, se usa el texto.
    sin_numero = {**_crudo("1"), "mto_deposito": None, "mto_deposito_desc": "1,250.50"}
    assert normalizar_detraccion(sin_numero, "pagosMasivos")["monto"] == 1250.5


def test_lectura_acumula_sin_duplicar(db_session):
    from tests.test_deudas import _empresa, _tenant

    empresa = _empresa(db_session, _tenant(db_session))
    ahora = datetime.now(timezone.utc)
    lectura = [normalizar_detraccion(_crudo("A1"), "pagosIndividuales"), normalizar_detraccion(_crudo("A2", monto=640.0), "pagosIndividuales")]
    assert aplicar_lectura_detracciones(db_session, empresa.id, lectura, ahora) == 2
    db_session.commit()
    # Otra busqueda (otro rango) trae A2 de nuevo y una nueva: A1 se conserva.
    otra = [normalizar_detraccion(_crudo("A2", monto=640.0), "pagosIndividuales"), normalizar_detraccion(_crudo("A3"), "pagosIndividuales")]
    aplicar_lectura_detracciones(db_session, empresa.id, otra, ahora)
    db_session.commit()
    assert sorted(p.num_constancia for p in db_session.query(DetraccionPago)) == ["A1", "A2", "A3"]


def test_busqueda_y_listado(client, db_session):
    from tests.test_deudas import _crear_empresa, _registrar

    headers = _registrar(client)
    empresa_id = _crear_empresa(client, headers, "20101281702")
    url = f"/empresas/{empresa_id}/detracciones/consultar"

    hoy = datetime.now(timezone(timedelta(hours=-5))).date()  # la validacion usa la fecha de Lima
    assert client.post(url, json={}, headers=headers).status_code == 400
    assert client.post(url, json={"fecha_desde": str(hoy), "fecha_hasta": str(hoy - timedelta(days=1))}, headers=headers).status_code == 400
    assert client.post(url, json={"fecha_desde": str(hoy - timedelta(days=400)), "fecha_hasta": str(hoy)}, headers=headers).status_code == 400
    assert client.post(url, json={"periodo": "2026-03", "tipos_cuenta": ["9"]}, headers=headers).status_code == 400

    r = client.post(
        url,
        json={"fecha_desde": str(hoy - timedelta(days=60)), "fecha_hasta": str(hoy), "tipos_cuenta": ["1", "2"], "tipos_pago": ["pagosIndividuales"]},
        headers=headers,
    )
    assert r.status_code == 202, r.text
    assert r.json()["estado"] == "pendiente" and r.json()["tipos_cuenta"] == "1,2"
    # Con una en curso no se encola otra: devuelve la misma.
    assert client.post(url, json={"periodo": "2026-03"}, headers=headers).json()["id"] == r.json()["id"]
    assert db_session.query(ConsultaDetraccionesJob).count() == 1

    aplicar_lectura_detracciones(
        db_session, empresa_id,
        [
            normalizar_detraccion(_crudo("B1", fecha="2026-03-19", periodo="202603"), "pagosIndividuales"),
            normalizar_detraccion(_crudo("B2", proveedor_ruc="20605775307", fecha="2026-03-31", periodo="202603"), "pagosIndividuales"),
            normalizar_detraccion(_crudo("B3", fecha="2026-02-06", periodo="202602"), "pagosIndividuales"),
        ],
        datetime.now(timezone.utc),
    )
    db_session.commit()
    datos = client.get(f"/empresas/{empresa_id}/detracciones?periodo=2026-03", headers=headers).json()
    assert [d["num_constancia"] for d in datos["depositos"]] == ["B2", "B1"]
    assert datos["busqueda"]["estado"] == "pendiente"
    por_fecha = client.get(f"/empresas/{empresa_id}/detracciones?fecha_desde=2026-02-01&fecha_hasta=2026-03-20", headers=headers).json()
    assert {d["num_constancia"] for d in por_fecha["depositos"]} == {"B1", "B3"}
