"""Liquidacion en vivo, Bloque 1: lectores de SUNAT, como se guarda lo leido y los endpoints de lecturas (datos ficticios)."""
import io
import uuid
import zipfile
from datetime import date, datetime, timezone

from sqlalchemy.orm import sessionmaker

import app.jobs_liquidacion as jobs_liquidacion
import app.routers.liquidacion as liquidacion
import lectores_liquidacion
from app.aduanas_lc import extraer_detalle, extraer_listado, meses
from app.models import (
    LiquidacionComprobante, LiquidacionCuentaControl, LiquidacionDeclaracion, LiquidacionEmpresa, LiquidacionLectura,
    LiquidacionRetencionPercepcion,
)
from app.security import cifrar_clave_sol
from app.sire_api import leer_archivo_propuesta, normalizar_comprobante
from lectores_liquidacion import (
    extraer_cuenta_control, normalizar_0621, normalizar_comprobante_recibido, tramos_anuales,
)
from tests.test_rbac_miembro import _armar_tenant_con_miembro

AHORA = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)


def _zip(texto: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("propuesta.txt", texto)
    return buf.getvalue()


def test_propuesta_del_sire_ventas_y_compras():
    rvie = (
        "﻿Ruc|Periodo|CAR SUNAT|Fecha de emisión|Tipo CP/Doc.|Serie del CDP|Nro CP o Doc. Nro Inicial (Rango)|"
        "Nro Doc Identidad|Apellidos Nombres/ Razón Social|Valor Facturado Exportación|BI Gravada|Dscto BI|IGV / IPM|"
        "Dscto IGV / IPM|Mto Exonerado|Mto Inafecto|Total CP|Moneda\n"
        "20111111111|202610|20111111111F001000001|05/10/2026|01|F001|1|20999999991|CLIENTE UNO|0.00|1000.00|0.00|"
        "180.00|0.00|0.00|50.00|1230.00|PEN\n"
        "20111111111|202610|20111111111F001000002|06/10/2026|07|F001|2|20999999991|CLIENTE UNO|0.00|0.00|-100.00|"
        "0.00|-18.00|0.00|0.00|-118.00|PEN\n"
    )
    filas = [normalizar_comprobante("RVIE", f, "2026-10") for f in leer_archivo_propuesta(_zip(rvie))]
    assert len(filas) == 2
    assert (filas[0]["car_sunat"], filas[0]["fecha_emision"], filas[0]["base_gravada"], filas[0]["igv"]) == (
        "20111111111F001000001", "2026-10-05", 1000.0, 180.0)
    assert (filas[0]["no_gravado"], filas[0]["nombre_contraparte"], filas[0]["periodo"]) == (50.0, "CLIENTE UNO", "2026-10")
    assert (filas[1]["descuento_base"], filas[1]["descuento_igv"]) == (-100.0, -18.0)

    # Compras: la columna del proveedor viene con doble espacio y sin CAR se arma una clave.
    rce = (
        "RUC|Apellidos y Nombres o Razón social|Periodo|CAR SUNAT|Fecha de emisión|Tipo CP/Doc.|Serie del CDP|"
        "Nro CP o Doc. Nro Inicial (Rango)|Nro Doc Identidad|Apellidos Nombres/ Razón  Social|BI Gravado DG|IGV / IPM DG|"
        "BI Gravado DGNG|IGV / IPM DGNG|Valor Adq. NG|Total CP|Moneda|COD. DAM O DSI|Detracción\n"
        "20111111111|EMPRESA|202610||10/10/2026|01|E001|77|20888888881|PROVEEDOR SAC|500.00|90.00|0|0|10.00|600.00|PEN||1\n"
    )
    (compra,) = [normalizar_comprobante("RCE", f, "2026-10") for f in leer_archivo_propuesta(_zip(rce))]
    assert compra["car_sunat"] == "01-E001-77-20888888881"
    assert (compra["nombre_contraparte"], compra["base_gravada"], compra["igv"], compra["no_gravado"], compra["detraccion"]) == (
        "PROVEEDOR SAC", 500.0, 90.0, 10.0, "1")


def test_0621_casillas_y_rango_por_anio():
    assert tramos_anuales("2025-09", "2026-10") == [("2025-09", "2025-12"), ("2026-01", "2026-10")]
    d = normalizar_0621(
        {"numOrd": "900000001", "perTri": "202609", "descTipoDecla": "1", "strFecPres": "20/10/2026"},
        {"C131": "1800.00 ", "C184": "-250.00 ", "C13": "10/20/2026", "C894": "0.0150", "otro": "x"},
    )
    assert d == {
        "num_orden": "900000001", "periodo": "2026-09", "rectificatoria": True, "fecha_presentacion": "2026-10-20",
        "casillas": {"131": 1800.0, "184": -250.0, "13": "10/20/2026", "894": 0.015},
    }


def test_comprobante_recibido_revertido_no_cuenta():
    # 05/10/2026 00:30 en Lima = 05:30 UTC: la fecha es la de Lima.
    ms = int(datetime(2026, 10, 5, 5, 30, tzinfo=timezone.utc).timestamp() * 1000)
    crudo = {"numRuc": "20777777771", "numSerieCpe": "R001", "numCpe": 15, "fechaEmision": ms,
             "montoTotalRetenido": 30.5, "codEstadoCpe": "01"}
    r = normalizar_comprobante_recibido(crudo, "retenciones")
    assert (r["documento"], r["periodo"], r["fecha_emision"], r["monto"], r["cuenta"]) == ("R001-15", "2026-10", "2026-10-05", 30.5, True)
    assert normalizar_comprobante_recibido({**crudo, "codEstadoCpe": "02"}, "retenciones")["cuenta"] is False
    # Percepciones: el nombre exacto del monto no se vio todavia; se toma el primer "montoTotal...".
    p = normalizar_comprobante_recibido({**crudo, "montoTotalRetenido": None, "montoTotalPercepcion": 12.0}, "percepciones")
    assert p["monto"] == 12.0


def test_cuenta_control_pantalla_de_resultados():
    html = (
        "<table><tr><td>Periodo Tributario</td><td>Monto Total Pagado S/</td><td>Monto Total de Retención S/</td></tr>"
        "<tr><td><a href='x'>202609</a></td><td class='m'>12,000</td><td>360</td><td>Descarga</td></tr>"
        "<tr><td>202608</td><td>1,000,500</td><td>30,015</td></tr></table>"
    )
    assert extraer_cuenta_control(html) == [
        {"periodo": "2026-09", "monto_base": 12000.0, "monto": 360.0},
        {"periodo": "2026-08", "monto_base": 1000500.0, "monto": 30015.0},
    ]
    assert extraer_cuenta_control("<p>Monto Total Pagado S/</p><table></table>") == []
    assert extraer_cuenta_control("<script>alert('No tiene Comprobantes')</script><p>Ingrese los datos</p>") is None


def test_aduanas_listado_y_detalle():
    listado = (
        "<p>RESULTADO DE CONSULTA 1 a 2 de 2</p><table>"
        "<tr><td><a href=\"/servlet/SGRdetLC?cadu=118&amp;fano=26&amp;nro=100\">118-26-100</a></td><td>25/09/2026</td>"
        "<td>25/09/2026</td><td>31/12/2999</td><td>500</td><td>0</td><td>IMPORTACIONES</td><td>01/10/2026</td></tr>"
        "<tr><td><a href=\"/servlet/SGRdetLC?cadu=235&amp;fano=26&amp;nro=7\">235-26-7</a></td><td>26/09/2026</td>"
        "<td>26/09/2026</td><td></td><td>1</td><td>0</td><td>OTROS</td><td>26/09/2026</td></tr></table>"
    )
    filas, total = extraer_listado(listado)
    assert total == 2 and [f["lc"] for f in filas] == ["118-26-100", "235-26-7"]
    assert (filas[0]["fecha_liquidacion"], filas[0]["fecha_cancelacion"], filas[0]["consulta_detalle"]) == (
        "2026-09-25", "2026-10-01", "cadu=118&fano=26&nro=100")

    detalle = (
        "<table><tr><td>Tipo L/C: 0038 PERCEPCION IGV</td></tr>"
        "<tr><td>Sustento : L/C COMPLEMENTARIA A LA DUA 118-2026-10-123456 DE FECHA 20260925</td></tr>"
        "<tr><td>Total Liquidado en SOLES : 500</td></tr>"
        "<tr><td>Código</td><td>Descripción</td><td>Monto</td></tr>"
        "<tr><td>0096</td><td>SUNAT PERCEPCION IGV</td><td>1,500.50</td></tr></table>"
    )
    assert extraer_detalle(detalle) == {
        "tipo": "0038", "moneda": "PEN", "dua": "118-2026-10-123456",
        "conceptos": [{"codigo": "0096", "descripcion": "SUNAT PERCEPCION IGV", "monto": 1500.5}],
    }
    assert meses(date(2026, 9, 15), date(2026, 11, 3)) == [
        (date(2026, 9, 15), date(2026, 9, 30)), (date(2026, 10, 1), date(2026, 10, 31)), (date(2026, 11, 1), date(2026, 11, 3)),
    ]


def test_rangos_de_cada_fuente():
    rango = jobs_liquidacion.rango_fuente
    noviembre = date(2026, 11, 3)
    assert rango("declaraciones", "2026-10", noviembre) == ("2025-09", "2026-10")
    assert rango("aduanas", "2026-10", noviembre) == ("2025-09", "2026-10")
    assert rango("cuenta_control", "2026-10", noviembre) == ("2025-10", "2026-09")
    assert rango("sire", "2026-10", noviembre) == ("2026-10", "2026-10")
    # En el mismo mes la cuenta de control llega hasta el mes pasado; y el historial empieza en enero si es antes.
    assert rango("cuenta_control", "2026-10", date(2026, 10, 28)) == ("2025-10", "2026-09")
    assert rango("declaraciones", "2026-02", noviembre) == ("2025-01", "2026-02")


def test_aplicar_declaraciones_marca_la_vigente(db_session):
    ctx_empresa = str(uuid.uuid4())
    original = {"num_orden": "100", "periodo": "2026-03", "rectificatoria": False, "fecha_presentacion": "2026-04-16",
                "casillas": {"184": 500.0}}
    rectificatoria = {**original, "num_orden": "101", "rectificatoria": True, "casillas": {"184": 450.0}}
    assert jobs_liquidacion.aplicar_declaraciones(db_session, ctx_empresa, [original], AHORA) == 1
    assert jobs_liquidacion.aplicar_declaraciones(db_session, ctx_empresa, [original, rectificatoria], AHORA) == 2
    db_session.commit()
    vigentes = {d.num_orden: d.vigente for d in db_session.query(LiquidacionDeclaracion)}
    assert vigentes == {"100": False, "101": True}


def test_aplicar_reemplaza_solo_el_rango_leido(db_session):
    emp = str(uuid.uuid4())
    comun = {"fecha_emision": "2026-10-01", "tipo_comprobante": "01", "serie": "F001", "doc_contraparte": "", "nombre_contraparte": "",
             "base_gravada": 100.0, "igv": 18.0, "descuento_base": 0.0, "descuento_igv": 0.0, "base_dgng": 0.0, "igv_dgng": 0.0,
             "no_gravado": 0.0, "exportacion": 0.0, "total": 118.0, "moneda": "PEN", "detraccion": "", "dam": "", "datos": {}}
    a = {**comun, "car_sunat": "A", "numero": "1", "periodo": "2026-10"}
    b = {**comun, "car_sunat": "B", "numero": "2", "periodo": "2026-10"}
    jobs_liquidacion.aplicar_comprobantes(db_session, emp, "RVIE", "2026-10", [a, b], AHORA)
    db_session.commit()
    jobs_liquidacion.aplicar_comprobantes(db_session, emp, "RVIE", "2026-10", [a], AHORA)  # B ya no esta en la propuesta
    db_session.commit()
    assert [c.car_sunat for c in db_session.query(LiquidacionComprobante)] == ["A"]

    def ret(doc, periodo):
        return {"ruc_agente": "20777777771", "documento": doc, "periodo": periodo, "fecha_emision": f"{periodo}-05",
                "monto": 10.0, "cuenta": True}
    jobs_liquidacion.aplicar_retenciones_percepciones(
        db_session, emp, "retencion", "comprobante", [ret("R1", "2026-09"), ret("R2", "2026-10")], "2026-09", "2026-10", AHORA)
    db_session.commit()
    # Una lectura solo de octubre sin R2 lo borra, pero no toca setiembre.
    jobs_liquidacion.aplicar_retenciones_percepciones(db_session, emp, "retencion", "comprobante", [], "2026-10", "2026-10", AHORA)
    db_session.commit()
    assert [r.documento for r in db_session.query(LiquidacionRetencionPercepcion)] == ["R1"]

    filas = [{"periodo": "2026-09", "monto_base": 1000.0, "monto": 30.0, "tipo": "retencion", "ruc_agente": ""},
             {"periodo": "2026-08", "monto_base": 500.0, "monto": 15.0, "tipo": "percepcion", "ruc_agente": "20131312955"}]
    jobs_liquidacion.aplicar_cuenta_control(db_session, emp, filas, [("retencion", ""), ("percepcion", "20131312955")],
                                            "2025-10", "2026-09", AHORA)
    db_session.commit()
    # Si la consulta de percepciones falla, lo ya guardado de percepciones se mantiene.
    jobs_liquidacion.aplicar_cuenta_control(db_session, emp, filas[:1], [("retencion", "")], "2025-10", "2026-09", AHORA)
    db_session.commit()
    assert sorted((c.tipo, c.periodo) for c in db_session.query(LiquidacionCuentaControl)) == [
        ("percepcion", "2026-08"), ("retencion", "2026-09")]


def _preparar_empresa(client, db_session, con_api=True):
    ctx = _armar_tenant_con_miembro(client, db_session)
    client.post(f"/liquidacion/empresas/{ctx['empresa_asignada_id']}/activar", json={"activa": True}, headers=ctx["headers_admin"])
    if con_api:
        client.put(f"/empresas/{ctx['empresa_asignada_id']}/liquidacion/api",
                   json={"client_id": "cliente-123456789", "client_secret": "secreto-abcdefgh"}, headers=ctx["headers_miembro"])
    return ctx


def test_pedir_y_ver_lecturas(client, db_session, monkeypatch):
    encoladas = []
    monkeypatch.setattr(liquidacion, "encolar_lecturas", lambda lecturas: encoladas.append([l.fuente for l in lecturas]))
    ctx = _armar_tenant_con_miembro(client, db_session)
    emp = ctx["empresa_asignada_id"]
    url = f"/empresas/{emp}/liquidacion/lecturas"

    assert client.post(url, json={"periodo": "2026-10"}, headers=ctx["headers_miembro"]).status_code == 400  # sin activar
    client.post(f"/liquidacion/empresas/{emp}/activar", json={"activa": True}, headers=ctx["headers_admin"])
    assert client.post(url, json={"periodo": "2999-01"}, headers=ctx["headers_miembro"]).status_code == 400
    assert client.post(url, json={"periodo": "2026-13"}, headers=ctx["headers_miembro"]).status_code == 422

    # Sin credenciales de la API se lee todo menos el SIRE.
    r = client.post(url, json={"periodo": "2026-10"}, headers=ctx["headers_miembro"])
    assert r.status_code == 200, r.text
    assert encoladas == [["declaraciones", "retenciones", "percepciones", "cuenta_control", "aduanas"]]
    assert r.json()["en_curso"] is True and {l["estado"] for l in r.json()["lecturas"]} == {"pendiente"}
    assert client.post(url, json={"periodo": "2026-10"}, headers=ctx["headers_miembro"]).status_code == 409
    assert client.post(url, json={"periodo": "2026-10", "fuentes": ["sire"]}, headers=ctx["headers_admin"]).status_code == 400

    vista = client.get(f"{url}?periodo=2026-10", headers=ctx["headers_miembro"]).json()
    assert vista["puede_leer"] is True and len(vista["lecturas"]) == 5
    assert vista["resumen"]["ventas"] == {"cantidad": 0, "base": 0, "igv": 0}

    # La otra empresa no es del miembro: no la ve.
    assert client.get(f"/empresas/{ctx['empresa_ajena_id']}/liquidacion/lecturas?periodo=2026-10",
                      headers=ctx["headers_miembro"]).status_code == 404


def test_trabajo_de_lecturas(client, db_session, monkeypatch):
    ctx = _preparar_empresa(client, db_session)
    emp = ctx["empresa_asignada_id"]
    monkeypatch.setattr(jobs_liquidacion, "SessionLocal", sessionmaker(bind=db_session.get_bind(), autoflush=False))
    monkeypatch.setattr(jobs_liquidacion, "_esperar_turno_sire", lambda: None)
    monkeypatch.setattr(jobs_liquidacion, "obtener_token", lambda *a: "token")
    llamadas = []

    def _0621(**kw):
        llamadas.append(("0621", kw["desde"], kw["hasta"]))
        kw["on_progreso"]("leyendo_declaraciones")
        return {"ok": True, "error": None, "declaraciones": [
            {"num_orden": "1", "periodo": "2026-09", "rectificatoria": False, "fecha_presentacion": "2026-10-16", "casillas": {"184": 10.0}},
        ]}

    def _sol(**kw):
        llamadas.append(("sol", kw["retenciones"], kw["cuenta_control"]))
        kw["on_progreso"]("autenticando")
        kw["on_progreso"]("leyendo_retenciones")
        return {"ok": True, "error": None, "resultados": {
            "retenciones": {"ok": True, "error": None, "filas": [
                {"ruc_agente": "20777777771", "documento": "R001-1", "periodo": "2026-10", "fecha_emision": "2026-10-05", "monto": 30.0, "cuenta": True},
            ]},
            "percepciones": {"ok": False, "error": "SUNAT no devolvio la consulta", "filas": []},
            "cuenta_control": {"ok": True, "error": None, "grupos": [("retencion", "")], "filas": [
                {"periodo": "2026-09", "monto_base": 1000.0, "monto": 30.0, "tipo": "retencion", "ruc_agente": ""},
            ]},
        }}

    def _propuesta(token, libro, periodo):
        base = {"fecha_emision": "2026-10-01", "tipo_comprobante": "01", "serie": "F001", "numero": "1", "doc_contraparte": "",
                "nombre_contraparte": "", "base_gravada": 100.0, "igv": 18.0, "descuento_base": 0.0, "descuento_igv": 0.0,
                "base_dgng": 0.0, "igv_dgng": 0.0, "no_gravado": 0.0, "exportacion": 0.0, "total": 118.0, "moneda": "PEN",
                "detraccion": "", "dam": "", "datos": {}, "periodo": periodo}
        return [{**base, "car_sunat": f"{libro}-1"}, {**base, "car_sunat": f"{libro}-2"}]

    monkeypatch.setattr(lectores_liquidacion, "leer_declaraciones_0621", _0621)
    monkeypatch.setattr(lectores_liquidacion, "leer_menu_sol", _sol)
    monkeypatch.setattr(jobs_liquidacion, "leer_percepciones_importacion", lambda ruc, desde, hasta: [])
    monkeypatch.setattr(jobs_liquidacion, "descargar_propuesta", _propuesta)
    monkeypatch.setattr(jobs_liquidacion, "hoy_peru", lambda: date(2026, 11, 3))
    monkeypatch.setattr(liquidacion, "encolar_lecturas", lambda lecturas: None)

    lecturas = jobs_liquidacion.crear_lecturas(db_session, emp, None, "2026-10", list(jobs_liquidacion.FUENTES))
    db_session.commit()
    jobs_liquidacion.ejecutar_lecturas_liquidacion([l.id for l in lecturas])

    db_session.expire_all()
    estado = {l.fuente: (l.estado, l.registros_leidos) for l in db_session.query(LiquidacionLectura)}
    assert estado == {
        "declaraciones": ("completado", 1), "retenciones": ("completado", 1), "percepciones": ("error", 0),
        "cuenta_control": ("completado", 1), "aduanas": ("completado", 0), "sire": ("completado", 4),
    }
    assert ("sol", (date(2026, 10, 1), date(2026, 10, 31)), ("2025-10", "2026-09")) in llamadas
    assert db_session.query(LiquidacionComprobante).count() == 4

    vista = client.get(f"/empresas/{emp}/liquidacion/lecturas?periodo=2026-10", headers=ctx["headers_miembro"]).json()
    assert vista["en_curso"] is False
    assert vista["resumen"]["ventas"] == {"cantidad": 2, "base": 200.0, "igv": 36.0}
    assert vista["resumen"]["retenciones"] == {"cantidad": 1, "monto": 30.0}
    assert vista["resumen"]["declaraciones"] == {"cantidad": 1, "ultimo_periodo": "2026-09"}


def test_clave_rechazada_no_se_reintenta(client, db_session, monkeypatch):
    ctx = _preparar_empresa(client, db_session, con_api=False)
    emp = ctx["empresa_asignada_id"]
    monkeypatch.setattr(jobs_liquidacion, "SessionLocal", sessionmaker(bind=db_session.get_bind(), autoflush=False))
    monkeypatch.setattr(lectores_liquidacion, "leer_declaraciones_0621", lambda **kw: {
        "ok": False, "error": "SUNAT rechazó el usuario o la clave SOL", "declaraciones": [], "credenciales_rechazadas": True})

    def _no_debe_llamarse(**kw):
        raise AssertionError("no se debe volver a entrar con una clave rechazada")

    monkeypatch.setattr(lectores_liquidacion, "leer_menu_sol", _no_debe_llamarse)
    monkeypatch.setattr(jobs_liquidacion, "leer_percepciones_importacion", lambda ruc, desde, hasta: [])

    lecturas = jobs_liquidacion.crear_lecturas(db_session, emp, None, "2026-10", ["declaraciones", "retenciones", "aduanas"])
    db_session.commit()
    jobs_liquidacion.ejecutar_lecturas_liquidacion([l.id for l in lecturas])

    db_session.expire_all()
    estado = {l.fuente: (l.estado, l.error) for l in db_session.query(LiquidacionLectura)}
    assert estado["declaraciones"] == ("error", "SUNAT rechazó el usuario o la clave SOL")
    assert estado["retenciones"] == ("error", "SUNAT rechazó el usuario o la clave SOL")
    assert estado["aduanas"][0] == "completado"  # Aduanas no usa la clave
