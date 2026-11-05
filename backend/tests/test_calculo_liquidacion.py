"""Liquidacion en vivo, Bloque 2: calculo del IGV y la Renta del periodo, tablero y panel (datos ficticios)."""
from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.calculo_liquidacion import casillas_declaradas, determinar_igv, porcentaje_renta, soles
from app.models import (
    CronogramaVencimiento, DeclaracionSunat, LiquidacionComprobante, LiquidacionDeclaracion, LiquidacionEmpresa,
    LiquidacionLectura, LiquidacionRetencionPercepcion,
)
from tests.test_rbac_miembro import _armar_tenant_con_miembro

LEIDO = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)


def _datos(**c):
    base = dict.fromkeys(("131", "178", "145", "171", "168", "179", "176", "185"), 0)
    return {**base, **c}


def test_orden_del_igv():
    # Como el 0621 de setiembre de una piloto: hay tributo, se restan percepciones y luego retenciones.
    r = determinar_igv(_datos(**{"131": 21000, "178": 11000, "145": 4000, "168": 500, "179": 700, "176": 800}))
    assert (r["140"], r["184"], r["164"], r["165"], r["681"]) == (10000, 6000, 0, 0, 4000)

    # Las percepciones alcanzan para todo el tributo: lo que sobra y todas las retenciones pasan al mes siguiente.
    r = determinar_igv(_datos(**{"131": 3000, "178": 2400, "171": 750, "179": 260, "176": 150}))
    assert (r["184"], r["164"], r["165"], r["681"]) == (600, 150, 410, 0)

    # Resultado negativo: el saldo a favor crece y nada se aplica.
    r = determinar_igv(_datos(**{"131": 1100, "178": 2500, "145": 2800, "171": 50, "168": 460, "179": 150, "176": 660}))
    assert (r["140"], r["184"], r["164"], r["165"], r["681"]) == (-1400, -4200, 510, 810, 0)


def test_redondeo_a_soles_enteros():
    assert (soles(10.5), soles(10.49), soles(-10.5), soles(None)) == (11, 10, -11, 0)


def test_casillas_de_la_ultima_declaracion_por_seccion():
    def decl(orden, fecha, casillas):
        return SimpleNamespace(num_orden=orden, fecha_presentacion=fecha, casillas=casillas)

    # Dos "originales": la segunda trae solo el IGV, asi que la Renta sigue siendo la de la primera.
    primera = decl("100", date(2026, 3, 18), {"131": 3000.0, "184": 2800.0, "301": 18000.0, "312": 180.0, "13": "x"})
    segunda = decl("200", date(2026, 5, 15), {"131": 3200.0, "184": 2900.0})
    assert casillas_declaradas([segunda, primera]) == {"131": 3200.0, "184": 2900.0, "301": 18000.0, "312": 180.0}


def test_porcentaje_de_renta_por_regimen():
    assert porcentaje_renta("especial", None, 0, 5500, False, None)[0] == 0.015
    assert porcentaje_renta("general", 0.0237, 0, 5500, False, None)[0] == 0.0237
    assert porcentaje_renta("general", 0.0045, 0, 5500, False, None)[0] == 0.015
    assert porcentaje_renta("general", None, 0, 5500, False, None)[0] == 0.015
    # MYPE: 1 % hasta 300 UIT en el ano; si ya se paso, el mayor entre coeficiente y 1.5 %.
    assert porcentaje_renta("mype", 0.02, 1_600_000, 5500, False, None)[0] == 0.01
    assert porcentaje_renta("mype", 0.02, 1_700_000, 5500, False, None)[0] == 0.02
    assert porcentaje_renta("mype", None, 10_000, 5500, True, None)[0] == 0.015
    # Otros regimenes: el porcentaje que se uso en el ultimo 0621.
    assert porcentaje_renta("amazonia", None, 0, 5500, False, 0.005)[0] == 0.005
    assert porcentaje_renta(None, None, 0, 5500, False, None)[0] is None


def _comprobante(emp, libro, n, tipo, base=0.0, igv=0.0, dscto_base=0.0, dscto_igv=0.0, datos=None, periodo="2026-10"):
    return LiquidacionComprobante(
        empresa_id=emp, periodo=periodo, libro=libro, fuente="propuesta", car_sunat=f"{libro}-{n}", tipo_comprobante=tipo,
        base_gravada=base, igv=igv, descuento_base=dscto_base, descuento_igv=dscto_igv, datos=datos or {},
    )


def _lectura(emp, fuente, desde, hasta):
    return LiquidacionLectura(empresa_id=emp, fuente=fuente, periodo_desde=desde, periodo_hasta=hasta, estado="completado",
                              finalizado_en=LEIDO)


def _empresa_con_octubre(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)
    emp = ctx["empresa_asignada_id"]
    client.post(f"/liquidacion/empresas/{emp}/activar", json={"activa": True}, headers=ctx["headers_admin"])
    db_session.get(LiquidacionEmpresa, emp).regimen = "mype"
    db_session.add_all([
        # Setiembre ya declarado: deja saldo a favor 2,000, percepciones 300 y retenciones 200.
        LiquidacionDeclaracion(empresa_id=emp, periodo="2026-09", num_orden="900", fecha_presentacion=date(2026, 10, 16),
                               casillas={"131": 5000.0, "178": 7000.0, "140": -2000.0, "184": -2000.0, "171": 300.0,
                                         "164": 300.0, "179": 200.0, "165": 200.0, "301": 40000.0, "315": 1.0, "312": 400.0}),
        LiquidacionDeclaracion(empresa_id=emp, periodo="2026-08", num_orden="800", fecha_presentacion=date(2026, 9, 16),
                               casillas={"184": 10.0, "301": 50000.0, "315": 1.0}),
        # Octubre: ventas con una nota de credito y una boleta inafecta.
        _comprobante(emp, "RVIE", 1, "01", base=10000.40, igv=1800.07),
        _comprobante(emp, "RVIE", 2, "07", base=-1000.0, igv=-180.0, dscto_base=-200.0, dscto_igv=-36.0),
        _comprobante(emp, "RVIE", 3, "03", datos={"mto inafecto": "500.00"}),
        # Compras: nacional, importacion (DAM) y una nota de credito.
        _comprobante(emp, "RCE", 1, "01", base=2000.0, igv=360.0),
        _comprobante(emp, "RCE", 2, "50", base=1000.0, igv=180.0),
        _comprobante(emp, "RCE", 3, "07", base=-100.0, igv=-18.0),
        LiquidacionRetencionPercepcion(empresa_id=emp, tipo="percepcion", origen="comprobante", documento="P001-1",
                                       periodo="2026-10", monto=50.0, cuenta=True),
        LiquidacionRetencionPercepcion(empresa_id=emp, tipo="percepcion", origen="aduanas", documento="LC-1",
                                       periodo="2026-10", monto=70.0, cuenta=True),
        LiquidacionRetencionPercepcion(empresa_id=emp, tipo="percepcion", origen="aduanas", documento="LC-2",
                                       periodo="2026-10", monto=999.0, cuenta=False),  # sin pagar
        LiquidacionRetencionPercepcion(empresa_id=emp, tipo="retencion", origen="comprobante", documento="R001-1",
                                       periodo="2026-10", monto=80.0, cuenta=True),
        LiquidacionRetencionPercepcion(empresa_id=emp, tipo="retencion", origen="comprobante", documento="R001-2",
                                       periodo="2026-10", monto=1000.0, cuenta=False),  # revertida
        DeclaracionSunat(empresa_id=emp, periodo="2026-10", formulario="1662", num_orden="1", cod_tributo="3121", importe_pagado=50.0),
        DeclaracionSunat(empresa_id=emp, periodo="2026-10", formulario="1662", num_orden="2", cod_tributo="1011", importe_pagado=10.0),
        CronogramaVencimiento(periodo_tributario="2026-10", grupo="1", tipo="mensual",
                              fecha_vencimiento=datetime(2026, 11, 16, tzinfo=timezone.utc)),
        _lectura(emp, "sire", "2026-10", "2026-10"),
        _lectura(emp, "retenciones", "2026-10", "2026-10"),
        _lectura(emp, "percepciones", "2026-10", "2026-10"),
        _lectura(emp, "aduanas", "2025-09", "2026-10"),
        _lectura(emp, "declaraciones", "2025-09", "2026-10"),
    ])
    db_session.commit()
    return ctx, emp


def test_calculo_del_periodo(client, db_session):
    ctx, emp = _empresa_con_octubre(client, db_session)
    r = client.get(f"/empresas/{emp}/liquidacion/calculo?periodo=2026-10", headers=ctx["headers_miembro"])
    assert r.status_code == 200
    calculo = r.json()
    c = calculo["casillas"]
    # Ventas: la nota de credito resta en 100 y 101; sus descuentos van a 102 y 103.
    assert (c["100"], c["101"], c["102"], c["103"], c["109"], c["131"]) == (9000, 1620, 200, 36, 500, 1584)
    assert (c["108"], c["115"], c["178"]) == (342, 180, 522)
    # 1584 - 522 = 1062; menos el saldo a favor de setiembre (2000) = -938.
    assert (c["140"], c["145"], c["184"]) == (1062, 2000, -938)
    # Percepciones: comprobante + Aduanas pagada, sin la pendiente. Retenciones sin la revertida.
    assert (c["171"], c["168"], c["164"], c["179"], c["176"], c["165"], c["681"], c["185"]) == (120, 300, 420, 80, 200, 280, 0, 10)
    assert (calculo["igv_por_pagar"], calculo["saldo_a_favor"]) == (0, 938)
    # Renta MYPE: 50,000 + 40,000 + 9,300 en el ano, bajo el tope: 1 %, menos el pago ya hecho.
    assert (c["301"], c["312"], c["317"], calculo["renta_porcentaje"], calculo["renta_por_pagar"]) == (9300, 93, 50, 0.01, 43)
    assert calculo["vence"] == "2026-11-16"
    assert calculo["hay_datos"] is True and calculo["declarado"] is None
    lineas = {l["casilla"]: l for l in calculo["lineas_igv"]}
    assert lineas["145"]["fuente"] == "0621 de setiembre 2026 (orden 900)"
    assert lineas["178"]["signo"] == -1 and lineas["681"]["tipo"] == "total"
    assert calculo["avisos"] == ["Percepciones de importación por S/ 999 todavía sin pagar: no se restan hasta que se paguen."]

    # "Como se llega al monto" en lenguaje simple: las lineas suman el resultado.
    monto = calculo["lineas_monto"]
    assert [(l["concepto"], l["monto"], l["signo"]) for l in monto] == [
        ("IGV de ventas gravadas", 1584, 1), ("Crédito fiscal de compras", 522, -1),
        ("Saldo a favor del mes anterior", 2000, -1), ("Percepciones del mes y no aplicadas", 0, -1),
        ("Retenciones del mes y no aplicadas", 0, -1), ("Saldo a favor", 938, 1),
    ]
    assert sum(l["monto"] * l["signo"] for l in monto[:-1]) == -938
    assert monto[0]["fuente"] == "SIRE ventas · 3 comprobantes · base S/ 8,800"
    assert monto[1]["fuente"] == "SIRE compras · 3 comprobantes · incluye importaciones (IGV S/ 180)"
    assert monto[3]["nota"] == "S/ 420 no alcanzan a aplicarse: pasan al mes siguiente"
    # Comparacion con los 0621 presentados: no hay octubre 2025; setiembre y agosto no dejaron IGV a pagar.
    assert calculo["comparacion"] == [
        {"concepto": "Octubre 2025 (mismo mes)", "periodo": "2025-10", "igv": None},
        {"concepto": "Setiembre 2026 (mes anterior)", "periodo": "2026-09", "igv": 0},
        {"concepto": "Promedio de los últimos 2 meses declarados", "periodo": None, "igv": 0},
    ]

    # Un periodo ya declarado muestra lo declarado al lado.
    setiembre = client.get(f"/empresas/{emp}/liquidacion/calculo?periodo=2026-09", headers=ctx["headers_miembro"]).json()
    assert setiembre["declarado"]["num_orden"] == "900"
    assert {l["casilla"]: l["declarado"] for l in setiembre["lineas_igv"]}["184"] == -2000

    # Noviembre sin 0621 de octubre: arrastra el estimado de octubre.
    noviembre = client.get(f"/empresas/{emp}/liquidacion/calculo?periodo=2026-11", headers=ctx["headers_miembro"]).json()
    cn = noviembre["casillas"]
    assert (cn["145"], cn["168"], cn["176"]) == (938, 420, 280)
    assert {l["casilla"]: l["fuente"] for l in noviembre["lineas_igv"]}["145"] == "estimado de octubre 2026 (aún sin 0621)"
    assert noviembre["hay_datos"] is False

    # Una empresa que el miembro no ve.
    assert client.get(f"/empresas/{ctx['empresa_ajena_id']}/liquidacion/calculo?periodo=2026-10",
                      headers=ctx["headers_miembro"]).status_code == 404


def test_credito_sin_ventas_gravadas_y_con_prorrata(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)
    emp = ctx["empresa_asignada_id"]
    client.post(f"/liquidacion/empresas/{emp}/activar", json={"activa": True}, headers=ctx["headers_admin"])
    db_session.add_all([
        LiquidacionDeclaracion(empresa_id=emp, periodo="2026-09", num_orden="900", fecha_presentacion=date(2026, 10, 16),
                               casillas={"105": 90000.0, "113": 30000.0, "173": 0.25, "301": 90000.0, "315": 1.5}),
        # Octubre: solo ventas exoneradas; el SIRE propone las compras con IGV.
        _comprobante(emp, "RVIE", 1, "01", datos={"mto exonerado": "80000.00"}),
        _comprobante(emp, "RCE", 1, "01", base=10000.0, igv=1800.0),
        # Noviembre: algo de ventas gravadas, se aplica la prorrata del 0621 de setiembre.
        _comprobante(emp, "RVIE", 2, "01", base=1000.0, igv=180.0, periodo="2026-11"),
        _comprobante(emp, "RCE", 2, "01", base=4000.0, igv=720.0, periodo="2026-11"),
        _lectura(emp, "sire", "2026-10", "2026-10"),
    ])
    db_session.commit()
    octubre = client.get(f"/empresas/{emp}/liquidacion/calculo?periodo=2026-10", headers=ctx["headers_admin"]).json()
    assert (octubre["casillas"]["105"], octubre["casillas"]["108"], octubre["casillas"]["178"]) == (80000, 1800, 0)
    assert any("no da crédito fiscal" in a for a in octubre["avisos"])
    noviembre = client.get(f"/empresas/{emp}/liquidacion/calculo?periodo=2026-11", headers=ctx["headers_admin"]).json()
    assert noviembre["casillas"]["178"] == 180  # 720 x 0.25


def test_base_de_renta_con_la_proporcion_del_ultimo_0621(client, db_session):
    # Quien vende por cuenta de otros declara como ingreso solo su comision: 1 % de las ventas.
    ctx = _armar_tenant_con_miembro(client, db_session)
    emp = ctx["empresa_asignada_id"]
    client.post(f"/liquidacion/empresas/{emp}/activar", json={"activa": True}, headers=ctx["headers_admin"])
    db_session.get(LiquidacionEmpresa, emp).regimen = "general"
    db_session.add_all([
        LiquidacionDeclaracion(empresa_id=emp, periodo="2026-09", num_orden="900", fecha_presentacion=date(2026, 10, 16),
                               casillas={"105": 400000.0, "301": 4000.0, "315": 1.5, "312": 60.0}),
        _comprobante(emp, "RVIE", 1, "03", datos={"mto exonerado": "500000.00"}),
        _lectura(emp, "sire", "2026-10", "2026-10"),
    ])
    db_session.commit()
    calculo = client.get(f"/empresas/{emp}/liquidacion/calculo?periodo=2026-10", headers=ctx["headers_admin"]).json()
    assert (calculo["casillas"]["105"], calculo["casillas"]["301"], calculo["casillas"]["312"]) == (500000, 5000, 75)
    assert any("se usa la misma proporción" in a for a in calculo["avisos"])
    # La Renta proyectada usa la misma proporcion de las ventas.
    from app.calculo_liquidacion import calcular_periodo
    from app.models import Empresa
    p = calcular_periodo(db_session, db_session.get(Empresa, emp), "2026-10", hoy=date(2026, 10, 20))["proyeccion"]
    assert p["ventas_netas"] >= 500000 and p["renta"] == soles(soles(p["ventas_netas"] * 0.01) * 0.015)


def test_panel_por_vencimiento(client, db_session):
    ctx, emp = _empresa_con_octubre(client, db_session)
    panel = client.get("/liquidacion/panel?periodo=2026-10", headers=ctx["headers_admin"]).json()
    # La otra empresa del estudio no esta activada: no sale.
    assert [e["empresa_id"] for e in panel["empresas"]] == [emp]
    (fila,) = panel["empresas"]
    assert (fila["vence"], fila["igv_por_pagar"], fila["saldo_a_favor"], fila["renta_por_pagar"], fila["avisos"]) == (
        "2026-11-16", 0, 938, 43, 1)
    assert (fila["declarado"], fila["igv_declarado"], fila["regimen"]) == (False, None, "mype")
    assert client.get("/liquidacion/panel?periodo=2026-13", headers=ctx["headers_admin"]).status_code == 422


def test_serie_dia_a_dia(client, db_session):
    from app.calculo_liquidacion import serie_diaria
    from app.models import Empresa

    ctx = _armar_tenant_con_miembro(client, db_session)
    emp = ctx["empresa_asignada_id"]
    client.post(f"/liquidacion/empresas/{emp}/activar", json={"activa": True}, headers=ctx["headers_admin"])

    def con_fecha(comprobante, dia):
        comprobante.fecha_emision = date(2026, 10, dia) if dia else None
        return comprobante

    db_session.add_all([
        con_fecha(_comprobante(emp, "RVIE", 1, "01", base=1000.0, igv=180.0), 10),
        con_fecha(_comprobante(emp, "RVIE", 2, "01", base=2000.0, igv=360.0), 20),
        con_fecha(_comprobante(emp, "RCE", 1, "01", base=500.0, igv=90.0), 5),
        con_fecha(_comprobante(emp, "RCE", 2, "01", base=100.0, igv=18.0), None),  # sin fecha: cuenta desde el dia 1
        _lectura(emp, "sire", "2026-10", "2026-10"),
    ])
    db_session.commit()

    puntos = {p["fecha"].day: (p["ventas"], p["credito"], p["por_pagar"])
              for p in serie_diaria(db_session, db_session.get(Empresa, emp), "2026-10", date(2026, 10, 15))}
    assert len(puntos) == 15  # hasta hoy
    assert (puntos[1], puntos[5], puntos[10], puntos[15]) == ((0, 18, 0), (0, 108, 0), (180, 108, 72), (180, 108, 72))

    # El mes cerrado sale completo y el ultimo dia es el estimado del mes.
    r = client.get(f"/empresas/{emp}/liquidacion/serie?periodo=2026-10", headers=ctx["headers_miembro"]).json()
    assert len(r["puntos"]) == 31 and r["puntos"][-1] == {"fecha": "2026-10-31", "ventas": 540, "credito": 108, "por_pagar": 432}
    # Sin SIRE leido no hay serie.
    assert client.get(f"/empresas/{emp}/liquidacion/serie?periodo=2026-09", headers=ctx["headers_miembro"]).json()["puntos"] == []


def test_estado_del_mes_y_motivos_de_atencion():
    from app.calculo_liquidacion import _atencion, _estado_mes

    def linea(monto, declarado):
        return {"monto": monto, "declarado": declarado}

    assert _estado_mes(None, [], True) == ("en_curso", 0)
    assert _estado_mes({"131": 1.0}, [linea(100, 100)], False) == ("declarado", 0)
    assert _estado_mes({"131": 1.0}, [linea(100, 105), linea(50, None)], True) == ("conciliado", 0)
    assert _estado_mes({"131": 1.0}, [linea(100, 111), linea(50, 20)], True) == ("con_diferencias", 2)

    comparacion = [{"concepto": "Octubre 2025 (mismo mes)", "igv": 1000}, {"concepto": "Setiembre 2026 (mes anterior)", "igv": 1100}]
    leido = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)  # 9:00 a.m. en Lima
    # Sube 15 % frente al ano anterior (no frente al mes anterior); los datos son de ayer: todavia sirven.
    assert _atencion(1150, comparacion, None, 0, leido, date(2026, 11, 3)) == [
        "IGV 15 % más alto que Octubre 2025 (S/ 1,000)"]
    assert _atencion(1100, comparacion, None, 0, leido, date(2026, 11, 4)) == [
        "Los datos del SIRE son del 02/11: no se han vuelto a leer"]
    # Ya declarado: solo cuentan las diferencias con el 0621.
    assert _atencion(5000, comparacion, {"131": 1.0}, 3, leido, date(2026, 11, 20)) == [
        "3 casilla(s) difieren en más de S/ 10 del 0621 presentado"]


def test_conciliacion_revisado_y_actualizar_todas(client, db_session, monkeypatch):
    import app.routers.liquidacion as liquidacion

    ctx, emp = _empresa_con_octubre(client, db_session)
    url = f"/empresas/{emp}/liquidacion"
    octubre = client.get(f"{url}/calculo?periodo=2026-10", headers=ctx["headers_miembro"]).json()
    assert octubre["estado_mes"] == "en_curso"
    assert octubre["atencion"][0] == "Falta configurar la API del SIRE"  # la empresa no tiene API
    assert octubre["revisado"] is None and octubre["puede_revisar"] is True

    # Aparece el 0621 de octubre: con el credito declarado distinto queda "con diferencias".
    db_session.add(LiquidacionDeclaracion(empresa_id=emp, periodo="2026-10", num_orden="1000", fecha_presentacion=date(2026, 11, 16),
                                          casillas={"131": 1584.0, "178": 600.0}))
    db_session.commit()
    octubre = client.get(f"{url}/calculo?periodo=2026-10", headers=ctx["headers_miembro"]).json()
    assert octubre["estado_mes"] == "con_diferencias"
    assert "1 casilla(s) difieren en más de S/ 10 del 0621 presentado" in octubre["atencion"]

    # "Revisado": el responsable lo marca; el panel y el tablero muestran la ultima marca.
    r = client.post(f"{url}/revisado", json={"periodo": "2026-10"}, headers=ctx["headers_miembro"])
    assert r.status_code == 200 and r.json()["usuario_nombre"]
    assert client.post(f"/empresas/{ctx['empresa_ajena_id']}/liquidacion/revisado", json={"periodo": "2026-10"},
                       headers=ctx["headers_miembro"]).status_code == 404
    assert client.get(f"{url}/calculo?periodo=2026-10", headers=ctx["headers_miembro"]).json()["revisado"] == r.json()
    (fila,) = client.get("/liquidacion/panel?periodo=2026-10", headers=ctx["headers_admin"]).json()["empresas"]
    assert (fila["estado_mes"], fila["estado_config"], fila["revisado"]["fecha"], fila["igv_681"]) == (
        "con_diferencias", "falta_api", r.json()["fecha"], 0)

    # "Actualizar todas": solo admin; el SIRE (si hay API) y Aduanas, y no repite una lectura en curso.
    encoladas = []
    monkeypatch.setattr(liquidacion, "encolar_lecturas", lambda lecturas, espera=None: encoladas.append([l.fuente for l in lecturas]))
    assert client.post("/liquidacion/panel/actualizar", json={"periodo": "2026-10"}, headers=ctx["headers_miembro"]).status_code == 403
    r = client.post("/liquidacion/panel/actualizar", json={"periodo": "2026-10"}, headers=ctx["headers_admin"])
    assert r.json() == {"encoladas": 1, "saltadas": 0, "minutos": 2} and encoladas == [["aduanas"]]
    assert client.post("/liquidacion/panel/actualizar", json={"periodo": "2026-10"}, headers=ctx["headers_admin"]).json()["saltadas"] == 1


def test_proyeccion_al_cierre(client, db_session):
    from app.calculo_liquidacion import calcular_periodo, dias_habiles
    from app.models import Empresa

    assert dias_habiles(date(2026, 11, 1), date(2026, 11, 30)) == 21
    ctx = _armar_tenant_con_miembro(client, db_session)
    emp = ctx["empresa_asignada_id"]
    client.post(f"/liquidacion/empresas/{emp}/activar", json={"activa": True}, headers=ctx["headers_admin"])

    def declarada(periodo, ventas, credito):
        return LiquidacionDeclaracion(empresa_id=emp, periodo=periodo, num_orden=periodo, fecha_presentacion=date(2026, 1, 1),
                                      casillas={"131": ventas, "178": credito})

    def comprobante(libro, n, igv, fecha):
        c = _comprobante(emp, libro, n, "01", base=igv / 0.18, igv=igv, periodo="2026-11")
        c.fecha_emision = fecha
        return c

    db_session.add_all([
        declarada("2025-11", 2000.0, 1000.0),
        *(declarada(p, 1000.0, 500.0) for p in ("2026-08", "2026-09", "2026-10")),
        comprobante("RVIE", 1, 900.0, date(2026, 11, 10)),
        comprobante("RCE", 1, 180.0, date(2026, 10, 28)),  # de octubre, registrada en noviembre: no se proyecta
        comprobante("RCE", 2, 270.0, date(2026, 11, 5)),
        _lectura(emp, "sire", "2026-11", "2026-11"),
    ])
    db_session.commit()
    empresa = db_session.get(Empresa, emp)

    # Lunes 16/11: pasaron 11 de 21 dias habiles. Ritmo: ventas 900 / 0.524 = 1,718; credito 180 + 270 / 0.524 = 695.
    # Historial (6.6): ventas (2,000 + 1,000) / 2 = 1,500; credito (1,000 + 500) / 2 = 750. Mezcla con peso 0.52 (6.5).
    p = calcular_periodo(db_session, empresa, "2026-11", hoy=date(2026, 11, 16))["proyeccion"]
    assert (p["ventas"], p["credito"], p["igv"], p["saldo_a_favor"], p["peso_del_mes"]) == (1614, 721, 893, 0, 0.52)
    # Rango (6.7): promedio de 3 meses 1,000 - 500 = 500; ritmo 1,718 - 695 = 1,023.
    assert (p["minimo"], p["maximo"], p["solo_historial"], p["sin_base"]) == (500, 1023, False, False)

    assert calcular_periodo(db_session, empresa, "2026-11", hoy=date(2026, 11, 5))["proyeccion"]["solo_historial"] is True
    # Un mes que ya cerro no se proyecta.
    assert calcular_periodo(db_session, empresa, "2026-10", hoy=date(2026, 11, 16))["proyeccion"] is None


def test_ventas_proyectadas_mueven_la_proyeccion(client, db_session, monkeypatch):
    from app import calculo_liquidacion
    from app.calculo_liquidacion import calcular_periodo, guardar_foto
    from app.models import Empresa, LiquidacionCalculo
    from app.routers import liquidacion

    ctx = _armar_tenant_con_miembro(client, db_session)
    emp = ctx["empresa_asignada_id"]
    client.post(f"/liquidacion/empresas/{emp}/activar", json={"activa": True}, headers=ctx["headers_admin"])
    db_session.get(LiquidacionEmpresa, emp).regimen = "mype"

    def declarada(periodo, ventas, igv, credito):
        return LiquidacionDeclaracion(empresa_id=emp, periodo=periodo, num_orden=periodo, fecha_presentacion=date(2026, 1, 1),
                                      casillas={"100": ventas, "131": igv, "178": credito})

    def comprobante(libro, n, base, fecha):
        c = _comprobante(emp, libro, n, "01", base=base, igv=base * 0.18, periodo="2026-11")
        c.fecha_emision = fecha
        return c

    db_session.add_all([
        declarada("2025-11", 12000.0, 2160.0, 1000.0),
        *(declarada(p, 6000.0, 1080.0, 500.0) for p in ("2026-08", "2026-09", "2026-10")),
        comprobante("RVIE", 1, 5000.0, date(2026, 11, 10)),
        comprobante("RCE", 1, 1500.0, date(2026, 11, 5)),
        _lectura(emp, "sire", "2026-11", "2026-11"),
    ])
    db_session.commit()
    empresa = db_session.get(Empresa, emp)
    hoy = date(2026, 11, 16)
    monkeypatch.setattr(calculo_liquidacion, "hoy_peru", lambda: hoy)
    monkeypatch.setattr(liquidacion, "hoy_peru", lambda: hoy)

    # Calculadas: ritmo 5,000 / 0.524 = 9,545 mezclado con el historial (12,000 + 6,000) / 2 = 9,000 con peso 0.52.
    p = calcular_periodo(db_session, empresa, "2026-11", hoy=hoy)["proyeccion"]
    assert (p["ventas_al_dia"], p["ventas_mismo_mes"], p["ventas_calculadas"], p["ventas_escritas"]) == (5000, 12000, 9286, None)
    assert p["ventas_netas"] == 9286 and p["renta"] == 93  # MYPE 1 %
    igv_ventas = p["ventas"]

    # El responsable escribe 20,000: el IGV de ventas sale con la misma proporcion de la proyeccion y la Renta con el 1 %.
    url = f"/empresas/{emp}/liquidacion/ventas-proyectadas"
    r = client.put(url, json={"periodo": "2026-11", "monto": 20000}, headers=ctx["headers_miembro"])
    assert r.status_code == 200, r.text
    p = r.json()["proyeccion"]
    assert (p["ventas_netas"], p["ventas_calculadas"], p["ventas_escritas"]["monto"]) == (20000, 9286, 20000)
    assert p["ventas_escritas"]["usuario_nombre"]
    assert (p["ventas"], p["renta"], p["igv"]) == (soles(20000 * igv_ventas / 9286), 200, p["ventas"] - p["credito"])
    # Queda en la foto del dia.
    guardar_foto(db_session, emp, "2026-11", calcular_periodo(db_session, empresa, "2026-11", hoy=hoy), hoy)
    db_session.commit()
    foto = db_session.query(LiquidacionCalculo).filter_by(empresa_id=emp, periodo="2026-11").one()
    assert foto.fuentes["proyeccion"]["ventas_escritas"]["monto"] == 20000

    # Una cifra menor que lo ya emitido no baja de lo emitido.
    p = client.put(url, json={"periodo": "2026-11", "monto": 1000}, headers=ctx["headers_miembro"]).json()["proyeccion"]
    assert p["ventas_netas"] == 5000 and p["ventas"] == 900
    # Sin monto vuelve a la calculada.
    p = client.put(url, json={"periodo": "2026-11", "monto": None}, headers=ctx["headers_miembro"]).json()["proyeccion"]
    assert (p["ventas_netas"], p["ventas_escritas"]) == (9286, None)
    # Solo el mes en curso.
    assert client.put(url, json={"periodo": "2026-10", "monto": 1}, headers=ctx["headers_miembro"]).status_code == 400
