"""Fase 5: revision de compras, detracciones y credito fiscal (app/credito_compras.py), con datos ficticios."""
from datetime import date

from app.credito_compras import RevisionCompras
from app.detracciones_spot import habiles_hasta, plazo_deposito
from app.models import (
    DetraccionCobertura, DetraccionPago, LiquidacionComprobante, LiquidacionCompraDecision, LiquidacionLectura,
)
from app.scheduler_job import dia_habil_del_mes
from tests.test_calculo_liquidacion import LEIDO
from tests.test_rbac_miembro import _armar_tenant_con_miembro

RUC = "20111111111"


def _compra(emp, n, ruc, total, igv, periodo="2026-10", tipo="01", marca="", serie="F001"):
    return LiquidacionComprobante(
        empresa_id=emp, periodo=periodo, libro="RCE", fuente="propuesta", car_sunat=f"CAR-{n}", tipo_comprobante=tipo,
        serie=serie, numero=f"{n:08d}", doc_contraparte=ruc, nombre_contraparte=f"PROVEEDOR {n}", fecha_emision=date(2026, 10, 10),
        base_gravada=round(igv / 0.18, 2), igv=igv, total=total, detraccion=marca, datos={},
    )


def _deposito(emp, constancia, ruc, n, fecha, monto, codigo="037", serie="F001"):
    return DetraccionPago(
        empresa_id=emp, num_constancia=constancia, tipo_cuenta="1", fecha_pago=fecha, periodo="2026-10", tipo_comprobante="01",
        serie=serie, numero=str(n), ruc_proveedor=ruc, doc_adquiriente=RUC, monto=monto, tipo_bien=codigo,
    )


def test_plazo_y_dias_habiles():
    # 5.o dia habil del mes siguiente (5.2); el 1 de enero es feriado.
    assert plazo_deposito("2026-10") == date(2026, 11, 6)
    assert plazo_deposito("2026-12") == date(2027, 1, 8)
    assert habiles_hasta(date(2026, 11, 3), date(2026, 11, 6)) == 3
    assert habiles_hasta(date(2026, 11, 6), date(2026, 11, 6)) == 0
    assert habiles_hasta(date(2026, 11, 10), date(2026, 11, 6)) == -2
    assert [dia_habil_del_mes(date(2026, 11, d)) for d in (1, 2, 6, 7, 10)] == [0, 1, 5, 0, 7]


def _octubre(client, db_session):
    ctx = _armar_tenant_con_miembro(client, db_session)
    emp = ctx["empresa_asignada_id"]
    db_session.add_all([
        _compra(emp, 1, "20500000001", 11800, 1800, marca="D"),  # marca D del SIRE, sin deposito
        _compra(emp, 2, "20500000002", 5900, 900),  # deposito a tiempo (12 % = 708)
        _compra(emp, 3, "20500000003", 2360, 360),  # deposito tarde, en noviembre
        _compra(emp, 4, "20500000002", 1180, 180),  # proveedor con detracciones, sin deposito: por verificar
        _compra(emp, 5, "20500000009", 500, 90),  # menos de S/ 700
        _compra(emp, 6, "", 1180, 180, tipo="50"),  # DAM
        _compra(emp, 7, "20500000004", 3540, 540),  # se excluye a mano
        _compra(emp, 8, "20500000005", 10000, 1525),  # deposito menor al esperado
        _deposito(emp, "111", "20500000002", 2, date(2026, 10, 20), 708),
        _deposito(emp, "222", "20500000003", 3, date(2026, 11, 20), 94, codigo="027"),
        _deposito(emp, "333", "20500000005", 8, date(2026, 10, 25), 500),
        LiquidacionCompraDecision(empresa_id=emp, car_sunat="CAR-7", periodo="2026-10", credito="excluir", motivo="Gasto no deducible"),
    ])
    db_session.commit()
    return ctx, emp


def test_estado_de_cada_compra_y_credito_del_mes(client, db_session):
    _, emp = _octubre(client, db_session)
    compras = db_session.query(LiquidacionComprobante).filter_by(empresa_id=emp, periodo="2026-10").all()

    # Sin lectura de detracciones, lo vencido no se da por "no depositado": sigue en riesgo.
    sin_leer = RevisionCompras(db_session, emp, RUC, date(2026, 11, 25)).del_periodo("2026-10", compras)
    fila = next(f for f in sin_leer["filas"] if f["car"] == "CAR-1")
    assert (fila["detraccion_texto"], fila["credito"]) == ("Sin confirmar", "en_riesgo")

    db_session.add(DetraccionCobertura(empresa_id=emp, desde=date(2022, 1, 1), hasta=date(2026, 11, 24), carga_completa=True))
    db_session.commit()
    r = RevisionCompras(db_session, emp, RUC, date(2026, 11, 25)).del_periodo("2026-10", compras)
    filas = {f["car"]: f for f in r["filas"]}
    assert (filas["CAR-1"]["estado"], filas["CAR-1"]["credito"]) == ("vencida", "suspendido")
    assert (filas["CAR-2"]["detraccion_texto"], filas["CAR-2"]["credito"], filas["CAR-2"]["esperado"]) == ("Pagada a tiempo", "cuenta", 708)
    assert (filas["CAR-3"]["detraccion_texto"], filas["CAR-3"]["credito_texto"], filas["CAR-3"]["credito_periodo"]) == (
        "Pagada tarde", "Cuenta en noviembre", "2026-11")
    assert (filas["CAR-4"]["estado"], filas["CAR-4"]["credito"]) == ("verificar", "por_confirmar")
    assert (filas["CAR-5"]["estado"], filas["CAR-5"]["detraccion_nota"]) == ("no_sujeta", "Menos de S/ 700")
    assert (filas["CAR-6"]["estado"], filas["CAR-6"]["detraccion_nota"]) == ("no_sujeta", "IGV pagado en aduanas")
    assert (filas["CAR-7"]["grupo"], filas["CAR-7"]["credito"]) == ("excluido", "excluido")
    assert (filas["CAR-8"]["detraccion_texto"], filas["CAR-8"]["esperado"]) == ("Coincidencia dudosa", 1200)
    # Sale del credito de octubre lo suspendido, lo depositado tarde y lo excluido.
    assert r["ajuste"] == -(1800 + 360 + 540)
    resumen = r["resumen"]
    assert (resumen["suspendido"], resumen["excluido"], resumen["por_verificar"], resumen["registro"]) == (1800, 540, 2, 5575)
    assert resumen["credito_cuenta"] == 900 + 180 + 90 + 180 + 1525

    # En noviembre entra lo depositado tarde y se sigue viendo lo suspendido de octubre.
    nov = RevisionCompras(db_session, emp, RUC, date(2026, 11, 25)).del_periodo("2026-11", [])
    filas = {f["car"]: f for f in nov["filas"]}
    assert filas["CAR-3"]["credito_texto"] == "Cuenta (viene de octubre)" and filas["CAR-1"]["credito"] == "suspendido"
    assert (nov["ajuste"], nov["resumen"]["credito_viene"]) == (360, 360)

    # Antes del plazo: en riesgo y aviso de los dias habiles que faltan (5.14).
    temprano = RevisionCompras(db_session, emp, RUC, date(2026, 11, 3))
    r = temprano.del_periodo("2026-10", compras)
    assert next(f for f in r["filas"] if f["car"] == "CAR-1")["credito"] == "en_riesgo"
    assert r["ajuste"] == -(360 + 540)  # lo que esta en plazo sigue contando
    assert temprano.alertas(r) == [
        "Detracción por depositar: 1 factura(s), S/ 1,800 de crédito en riesgo; plazo hasta el 06/11 (faltan 3 días hábiles)"
    ]


def test_pantalla_de_compras_decisiones_y_reglas(client, db_session):
    ctx, emp = _octubre(client, db_session)
    # Un mes viejo: el plazo ya paso y las detracciones estan leidas, sin depender de la fecha de hoy.
    db_session.add_all([
        _compra(emp, 20, "20500000020", 11800, 1800, periodo="2025-01", marca="D"),
        LiquidacionLectura(empresa_id=emp, fuente="sire", periodo_desde="2025-01", periodo_hasta="2025-01",
                           estado="completado", finalizado_en=LEIDO),
        DetraccionCobertura(empresa_id=emp, desde=date(2022, 1, 1), hasta=date(2026, 11, 24), carga_completa=True),
    ])
    db_session.commit()
    h = ctx["headers_miembro"]
    url = f"/empresas/{emp}/liquidacion/compras"
    r = client.get(f"{url}?periodo=2025-01", headers=h)
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["hay_compras"] is True and datos["puede_decidir"] is True
    fila = datos["filas"][0]
    assert (fila["car"], fila["credito"], datos["resumen"]["suspendido"]) == ("CAR-20", "suspendido", 1800)
    calculo = client.get(f"/empresas/{emp}/liquidacion/calculo?periodo=2025-01", headers=h).json()
    assert calculo["casillas"]["178"] == 0 and calculo["compras"]["suspendido"] == 1800
    assert "menos S/ 1,800 por la revisión de compras" in calculo["lineas_igv"][3]["fuente"]

    # Incluir o excluir a mano exige motivo; "Otro" exige comentario.
    put = f"{url}/CAR-20"
    base = {"periodo": "2025-01", "lleva": "auto", "credito": "incluir", "motivo": "", "comentario": "", "constancia": ""}
    assert client.put(put, json=base, headers=h).status_code == 400
    assert client.put(put, json={**base, "motivo": "Otro"}, headers=h).status_code == 400
    r = client.put(put, json={**base, "motivo": "Detracción depositada (constancia en mano)", "constancia": "999"}, headers=h)
    assert r.status_code == 200, r.text
    fila = r.json()["filas"][0]
    assert (fila["credito"], fila["detraccion_texto"], fila["decision"]["constancia"]) == ("cuenta", "Según constancia", "999")
    assert client.get(f"/empresas/{emp}/liquidacion/calculo?periodo=2025-01", headers=h).json()["casillas"]["178"] == 1800

    # "Excluir siempre" crea la regla del proveedor; al quitarla vuelve a lo automatico (detraccion vencida).
    r = client.put(put, json={**base, "credito": "excluir_siempre", "motivo": "No relacionado con el negocio"}, headers=h).json()
    regla, = r["reglas"]
    assert (regla["regla"], regla["ruc_proveedor"], regla["desde_periodo"]) == ("excluir", "20500000020", "2025-01")
    client.put(put, json={**base, "credito": "auto"}, headers=h)
    assert client.get(f"{url}?periodo=2025-01", headers=h).json()["filas"][0]["credito_texto"] == "Excluido a mano"
    r = client.delete(f"/empresas/{emp}/liquidacion/reglas-proveedor/{regla['id']}?periodo=2025-01", headers=h).json()
    assert r["reglas"] == [] and r["filas"][0]["credito"] == "suspendido"

    # Una empresa que el miembro no ve.
    assert client.get(f"/empresas/{ctx['empresa_ajena_id']}/liquidacion/compras?periodo=2025-01", headers=h).status_code == 404
