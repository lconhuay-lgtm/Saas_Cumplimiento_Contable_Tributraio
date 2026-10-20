"""
Modulo Cumplimiento > Deudas (valores pendientes de pago) y reglas
compartidas de Cumplimiento: tramos de consulta, lectura de la respuesta de
SUNAT, historial de valores, empresas que no estan ACTIVO fuera del cuadro y
la regla de relectura automatica del SIRE.
"""
import json
from datetime import date, datetime, timedelta, timezone

from adapter import (
    _ultimo_periodo_consultable_valores, extraer_listado_valores, normalizar_valor, tramos_periodos,
)
from app.jobs import aplicar_lectura_valores
from app.models import ConsultaSireJob, CronogramaVencimiento, Empresa, Tenant, ValorDeuda
from app.scheduler_job import empresas_para_refresco_sire


def _crudo(num, etapa="En Cobranza Coactiva", cod_eta="03", saldo="899.00000", tipo="Orden de Pago"):
    """Un elemento de ListadoValores con los mismos nombres (y relleno de espacios) que manda SUNAT."""
    return {
        "numVal": f"{num}    ", "desCor": "OP" + " " * 58, "desLar": tipo + " " * 20, "perDoc": "202608",
        "codTri": "3121", "descLarTrib": "RENTA - REGIMEN MYPE TRIBUTARIO      ", "strFecEmi": "23/09/2026",
        "strFecNot": "23/09/2026", "desEst": "Pendiente", "codEta": cod_eta, "desEta": "Cobranza Coactiva    ",
        "desEtaBas": etapa + "    ", "desEtaAlt": "   ", "numExpCoa": "0290064992149    ", "mtoTri": 890.0,
        "montoInteresSolesAct": "9.00000", "saldoTotal": saldo, "saldoExigible": saldo,
    }


def test_tramos_de_seis_meses_hasta_el_mes_pasado():
    tramos = tramos_periodos("202001", "202609")
    assert len(tramos) == 14
    assert tramos[0] == ("202001", "202006")
    assert tramos[1] == ("202007", "202012")
    assert tramos[-1] == ("202607", "202609")
    assert tramos_periodos("202603", "202603") == [("202603", "202603")]


def test_ultimo_periodo_consultable_es_el_mes_anterior():
    lima = timezone(timedelta(hours=-5))
    assert _ultimo_periodo_consultable_valores(datetime(2026, 10, 20, tzinfo=lima)) == "202609"
    assert _ultimo_periodo_consultable_valores(datetime(2027, 1, 3, tzinfo=lima)) == "202612"


def test_extraer_listado_con_datos_en_latin1():
    """La plantilla de SUNAT es UTF-8 pero el JSON de los valores llega en Latin-1."""
    datos = json.dumps([{"numVal": "0230022911051", "desLar": "Resolución de Multa"}], ensure_ascii=False)
    html = (
        "<html><head><title>RESULTADO VALORES PENDIENTES</title></head><script>\n".encode("utf-8")
        + b"\t\tvar ListadoValores = " + datos.encode("latin-1") + b";\n\t\tvar Contribuyente = {};</script>"
    )
    listado = extraer_listado_valores(html)
    assert listado == [{"numVal": "0230022911051", "desLar": "Resolución de Multa"}]
    assert extraer_listado_valores(b"\t\tvar ListadoValores = [];\n") == []
    assert extraer_listado_valores(b"<html>Sesion expirada</html>") is None


def test_normalizar_valor():
    v = normalizar_valor(_crudo("0300015123569"))
    assert v["num_valor"] == "0300015123569"
    assert v["tipo"] == "OP"
    assert v["tipo_descripcion"] == "Orden de Pago"
    assert v["periodo"] == "2026-08"
    assert v["fecha_emision"] == "2026-09-23"
    assert v["etapa"] == "En Cobranza Coactiva"
    assert v["en_cobranza_coactiva"] is True
    assert v["num_expediente_coactivo"] == "0290064992149"
    assert v["saldo_total"] == 899.0
    assert v["interes"] == 9.0
    sin_coactiva = normalizar_valor({**_crudo("1"), "codEta": "01", "desEtaBas": "Notificado", "desEta": "Cobranza"})
    assert sin_coactiva["en_cobranza_coactiva"] is False


def _tenant(db):
    tenant = Tenant(nombre="Estudio")
    db.add(tenant)
    db.commit()
    return tenant


def _empresa(db, tenant, ruc="20101281702", estado=None):
    e = Empresa(tenant_id=tenant.id, ruc=ruc, razon_social=f"Empresa {ruc}", estado_contribuyente=estado)
    db.add(e)
    db.commit()
    return e


def test_historial_de_valores(db_session):
    empresa = _empresa(db_session, _tenant(db_session))
    t1 = datetime(2026, 10, 20, 13, 30, tzinfo=timezone.utc)
    lectura1 = [normalizar_valor(_crudo("A1")), normalizar_valor(_crudo("A2", etapa="Notificado", cod_eta="01"))]
    assert aplicar_lectura_valores(db_session, empresa.id, lectura1, t1) == {"vigentes": 2, "nuevos": 2}
    db_session.commit()

    # Dia 2: A2 paso a coactiva con mas saldo, A1 ya no aparece (se pago).
    t2 = t1 + timedelta(days=1)
    lectura2 = [normalizar_valor(_crudo("A2", saldo="950.00000"))]
    assert aplicar_lectura_valores(db_session, empresa.id, lectura2, t2) == {"vigentes": 1, "nuevos": 0}
    db_session.commit()
    valores = {v.num_valor: v for v in db_session.query(ValorDeuda)}
    assert valores["A1"].vigente is False
    assert valores["A1"].ya_no_aparece_desde.replace(tzinfo=timezone.utc) == t2
    assert [h["evento"] for h in valores["A1"].historial] == ["nuevo", "ya_no_aparece"]
    assert [h["evento"] for h in valores["A2"].historial] == ["nuevo", "cambio_etapa", "cambio_saldo"]
    assert valores["A2"].en_cobranza_coactiva is True
    assert valores["A2"].fecha_emision == date(2026, 9, 23)

    # Dia 3: A1 vuelve a aparecer (p. ej. se perdio un fraccionamiento).
    aplicar_lectura_valores(db_session, empresa.id, lectura1, t2 + timedelta(days=1))
    db_session.commit()
    a1 = db_session.query(ValorDeuda).filter(ValorDeuda.num_valor == "A1").one()
    assert a1.vigente is True and a1.ya_no_aparece_desde is None
    assert a1.historial[-1]["evento"] == "reaparecio"


def _registrar(client):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": "Estudio Deudas", "email": "admin@example.com", "password": "ClaveSegura123!"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _crear_empresa(client, headers, ruc):
    resp = client.post(
        "/empresas",
        json={"ruc": ruc, "razon_social": f"Empresa {ruc}", "usuario_sol": "x", "clave_sol": "x", "obligacion_igv_renta": False},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_cumplimiento_oculta_empresas_que_no_estan_activas(client, db_session):
    headers = _registrar(client)
    activa = _crear_empresa(client, headers, "20111111111")
    sin_leer = _crear_empresa(client, headers, "20222222222")
    baja = _crear_empresa(client, headers, "20333333333")
    suspendida = _crear_empresa(client, headers, "20444444444")
    for empresa_id, estado in ((activa, "ACTIVO"), (baja, "BAJA DE OFICIO"), (suspendida, "SUSPENSION TEMPORAL")):
        db_session.get(Empresa, empresa_id).estado_contribuyente = estado
    db_session.commit()
    aplicar_lectura_valores(db_session, activa, [normalizar_valor(_crudo("V1"))], datetime.now(timezone.utc))
    db_session.commit()

    deudas = client.get("/cumplimiento/deudas", headers=headers)
    assert deudas.status_code == 200, deudas.text
    filas = {f["empresa_id"]: f for f in deudas.json()["filas"]}
    assert set(filas) == {activa, sin_leer}
    assert filas[activa]["valores"][0]["num_valor"] == "V1"
    assert filas[activa]["valores"][0]["historial"][0]["evento"] == "nuevo"

    sire = client.get("/cumplimiento/sire", headers=headers)
    assert {f["empresa_id"] for f in sire.json()["filas"]} == {activa, sin_leer}


def test_refresco_sire_semanal_y_tras_vencimiento(db_session):
    tenant = _tenant(db_session)
    hoy = date(2026, 10, 20)
    nunca = _empresa(db_session, tenant, ruc="20100000010")  # grupo 0 (ultimo digito 0)
    reciente = _empresa(db_session, tenant, ruc="20100000015")  # grupo 4_5
    vieja = _empresa(db_session, tenant, ruc="20100000017")  # grupo 6_7
    vencio_ayer = _empresa(db_session, tenant, ruc="20100000012")  # grupo 2_3
    baja = _empresa(db_session, tenant, ruc="20100000018", estado="BAJA DEFINITIVA")

    def leida(empresa, dias_atras):
        db_session.add(ConsultaSireJob(
            empresa_id=empresa.id, estado="completado",
            finalizado_en=datetime(hoy.year, hoy.month, hoy.day, 15, tzinfo=timezone.utc) - timedelta(days=dias_atras),
        ))

    leida(reciente, 2)
    leida(vieja, 8)
    leida(vencio_ayer, 3)
    leida(baja, 30)
    db_session.add(CronogramaVencimiento(
        periodo_tributario="2026-09", grupo="2_3", tipo="sire",
        fecha_vencimiento=datetime(2026, 10, 19, tzinfo=timezone.utc),
    ))
    db_session.commit()

    elegidas = {e.ruc for e in empresas_para_refresco_sire(db_session, hoy=hoy)}
    assert elegidas == {nunca.ruc, vieja.ruc, vencio_ayer.ruc}

    # Una vez releida despues del vencimiento, ya no se vuelve a pedir.
    leida(vencio_ayer, 0)
    db_session.commit()
    assert vencio_ayer.ruc not in {e.ruc for e in empresas_para_refresco_sire(db_session, hoy=hoy)}
