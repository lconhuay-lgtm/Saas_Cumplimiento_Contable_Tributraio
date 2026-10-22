"""
Cumplimiento > Declaracion mensual: lectura de la "Consulta general de
declaraciones y pagos" de SUNAT, guardado por rango y el cuadro por anio.
"""
from datetime import date, datetime, timezone

from adapter import extraer_declaraciones
from app.jobs import aplicar_lectura_declaraciones
from app.models import CronogramaVencimiento, DeclaracionSunat


def _fila_html(periodo, form, orden, desc, fecha, banco="-", tributo="-", importe="0,00"):
    detalle = "-" if banco == "-" else '<a href="javascript:verDetalleTributos(1)"> Detalle de Tributos Pagados</a>'
    celdas = ["&nbsp;", periodo, form, orden, desc, fecha, banco, tributo, detalle, importe]
    return "<tr>" + "".join(f'<td class="bg">{c}</td>' for c in celdas) + "</tr>"


def _pagina(*filas):
    return (
        "<html><body><h3>DETALLE DE DECLARACIONES Y PAGOS</h3><table><tr><th>Periodo</th><th>N\xb0 Form</th></tr>"
        + "".join(filas)
        + "</table></body></html>"
    )


def test_extraer_declaraciones():
    html = _pagina(
        _fila_html("202608", "0621", "1207052856", "Simplificado IGV- Renta mensual", "17/09/2026"),
        _fila_html("202608", "1662", "1204164368", "BOLETA DE PAGO - VIRTUAL ", "31/08/2026", "DE CREDITO DEL PERU ", "8052", "17.522,50"),
    )
    filas = extraer_declaraciones(html)
    assert filas[0] == {
        "periodo": "2026-08", "formulario": "0621", "num_orden": "1207052856",
        "descripcion": "Simplificado IGV- Renta mensual", "fecha_presentacion": "2026-09-17",
        "banco": "", "cod_tributo": "", "importe_pagado": 0.0,
    }
    assert filas[1]["banco"] == "DE CREDITO DEL PERU"
    assert filas[1]["cod_tributo"] == "8052"
    assert filas[1]["importe_pagado"] == 17522.5
    assert extraer_declaraciones(_pagina()) == []  # rango sin declaraciones
    assert extraer_declaraciones("<html>Sesion expirada</html>") is None


def _decl(periodo, form, orden, fecha="2026-09-17", tributo="", importe=0.0):
    return {
        "periodo": periodo, "formulario": form, "num_orden": orden, "descripcion": "x",
        "fecha_presentacion": fecha, "banco": "", "cod_tributo": tributo, "importe_pagado": importe,
    }


def test_aplicar_lectura_reemplaza_solo_el_rango_leido(db_session):
    from tests.test_deudas import _empresa, _tenant

    empresa = _empresa(db_session, _tenant(db_session))
    ahora = datetime.now(timezone.utc)
    aplicar_lectura_declaraciones(
        db_session, empresa.id,
        [_decl("2025-12", "0621", "1"), _decl("2026-01", "0621", "2"), _decl("2026-01", "0601", "3")],
        "202001", "202601", ahora,
    )
    db_session.commit()
    # Segunda lectura solo de 2026-01: el 0601 ya no figura (SUNAT lo anulo) y
    # aparece una rectificatoria; 2025-12 queda fuera del rango y no se toca.
    leidos = aplicar_lectura_declaraciones(
        db_session, empresa.id,
        [_decl("2026-01", "0621", "2"), _decl("2026-01", "0621", "4", fecha="2026-03-02")],
        "202601", "202601", ahora,
    )
    db_session.commit()
    assert leidos == 2
    guardadas = {(d.periodo, d.formulario, d.num_orden) for d in db_session.query(DeclaracionSunat)}
    assert guardadas == {("2025-12", "0621", "1"), ("2026-01", "0621", "2"), ("2026-01", "0621", "4")}
    rectificatoria = db_session.query(DeclaracionSunat).filter(DeclaracionSunat.num_orden == "4").one()
    assert rectificatoria.fecha_presentacion == date(2026, 3, 2)


def test_cuadro_de_declaraciones(client, db_session):
    from tests.test_deudas import _crear_empresa, _registrar

    headers = _registrar(client)
    # La empresa se crea con la obligacion IGV-Renta activa (por defecto) y
    # sin planilla: el 0621 se espera siempre, el 0601 desde que presento uno.
    empresa_id = client.post(
        "/empresas",
        json={"ruc": "20444444444", "razon_social": "Empresa Decl", "usuario_sol": "x", "clave_sol": "x", "obligacion_igv_renta": True},
        headers=headers,
    ).json()["id"]
    aplicar_lectura_declaraciones(
        db_session, empresa_id,
        [
            _decl("2026-07", "0621", "10"),
            _decl("2026-08", "0621", "11"),
            _decl("2026-08", "0601", "12"),
            _decl("2026-08", "1662", "13", tributo="8052", importe=4880.0),
        ],
        "202001", "202609", datetime.now(timezone.utc),
    )
    db_session.add(CronogramaVencimiento(
        periodo_tributario="2026-09", grupo="4_5", tipo="mensual",
        fecha_vencimiento=datetime(2026, 10, 21, tzinfo=timezone.utc),
    ))
    db_session.commit()

    r = client.get("/cumplimiento/declaraciones?anio=2026", headers=headers)
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["anio"] == 2026 and datos["anios_disponibles"] == [2026]
    fila = next(f for f in datos["filas"] if f["empresa_id"] == empresa_id)
    assert fila["obligado_desde"] == {"0621": "2026-07", "0601": "2026-08"}
    periodos = {p["periodo"]: p for p in fila["periodos"]}
    assert set(periodos) == {"2026-07", "2026-08", "2026-09"}
    assert sorted(f["formulario"] for f in periodos["2026-08"]["formularios"]) == ["0601", "0621", "1662"]
    assert periodos["2026-09"]["formularios"] == [] and periodos["2026-09"]["vence_el"].startswith("2026-10-21")

    _crear_empresa(client, headers, "20111111111")  # obligacion IGV-Renta por defecto, sin historial
    fila_nueva = next(
        f for f in client.get("/cumplimiento/declaraciones?anio=2026", headers=headers).json()["filas"]
        if f["ruc"] == "20111111111"
    )
    assert fila_nueva["obligado_desde"]["0601"] is None


def test_marcar_no_obligada_a_plame(client, db_session):
    from app.models import EmpresaObligacion, TareaObligacion
    from app.tareas import revisar_obligacion_plame
    from tests.test_deudas import _registrar

    headers = _registrar(client)
    empresa_id = client.post(
        "/empresas",
        json={"ruc": "20555555555", "razon_social": "Sin trabajadores", "usuario_sol": "x", "clave_sol": "x", "obligacion_igv_renta": True},
        headers=headers,
    ).json()["id"]
    # Presento una PLAME hace un mes -> la deteccion le crea la obligacion y tiene una tarea pendiente.
    hace_un_mes = datetime.now(timezone.utc).replace(day=1)
    periodo = f"{hace_un_mes.year}-{hace_un_mes.month:02d}"
    aplicar_lectura_declaraciones(db_session, empresa_id, [_decl(periodo, "0601", "77")], "202001", periodo.replace("-", ""), datetime.now(timezone.utc))
    db_session.commit()
    assert revisar_obligacion_plame(db_session, empresa_id) == "creada"
    db_session.commit()
    ob = db_session.query(EmpresaObligacion).filter(EmpresaObligacion.empresa_id == empresa_id, EmpresaObligacion.tipo == "planilla").one()
    db_session.add(TareaObligacion(empresa_id=empresa_id, empresa_obligacion_id=ob.id, titulo="PLAME", tipo="planilla", periodo=periodo))
    db_session.commit()

    def fila():
        return next(f for f in client.get(f"/cumplimiento/declaraciones?anio={periodo[:4]}", headers=headers).json()["filas"] if f["empresa_id"] == empresa_id)

    assert fila()["obligado_desde"]["0601"] == periodo

    r = client.post(f"/empresas/{empresa_id}/declaraciones/control", json={"formulario": "0601", "controlar": False}, headers=headers)
    assert r.status_code == 200 and r.json()["tareas_borradas"] == 1
    assert fila()["obligado_desde"]["0601"] is None
    assert fila()["formularios_no_controlados"] == ["0601"]
    # La deteccion automatica respeta la decision del usuario.
    assert revisar_obligacion_plame(db_session, empresa_id) is None

    client.post(f"/empresas/{empresa_id}/declaraciones/control", json={"formulario": "0601", "controlar": True}, headers=headers)
    assert fila()["obligado_desde"]["0601"] == periodo and fila()["formularios_no_controlados"] == []
    assert client.post(f"/empresas/{empresa_id}/declaraciones/control", json={"formulario": "1662", "controlar": False}, headers=headers).status_code == 400
