"""
Obligacion de PLAME por recibos por honorarios recibidos (app/plame.py):
lectura de la Consulta Receptor de SUNAT, guardado por periodo, deteccion de
la obligacion, cuadro de Declaraciones, tarjeta de Empresas y revision semanal.
"""
from datetime import date, datetime, timezone

from adapter import extraer_rxh_recibidos
from app.models import ConsultaRxhJob, EmpresaObligacion, ReciboHonorario
from app.plame import aplicar_lectura_rxh, periodo_rxh_a_revisar, plame_desde, rango_del_periodo
from app.tareas import NOMBRE_PLAME_POR_RXH, revisar_obligacion_plame


def _fila_html(fecha, numero, estado, ruc, nombre, bruta, retencion="0.00", pendiente="0.00"):
    celdas = [fecha, "RH", f'<a href="javascript:escoger(0 )">{numero}</a>', estado, "RUC", ruc, nombre, "A", "NO", "SOLES",
              bruta, retencion, "0.00", "0.00", "0.00", "0.00", bruta, pendiente]
    return "<tr>" + "".join(f"<td>{c}</td>" for c in celdas) + "</tr>"


def _pagina(*filas, total=None, siguiente="1"):
    n = len(filas)
    return (
        f"<html><body><td>{1 if n else 1} a {n} de {total if total is not None else n}</td>"
        "<b>FECHA DESDE:</b> 01/10/2026 <table>" + "".join(filas) + "</table>"
        f'<form name="NavigFormNext"><input type="hidden" name="currPage" value="{siguiente}"></form></body></html>'
    )


def _recibo(numero, estado="NO ANULADO", fecha="2026-10-06", bruta=1000.0, ruc="10765113151"):
    return {
        "fecha_emision": fecha, "tipo": "RH", "numero": numero, "estado": estado, "doc_emisor": ruc,
        "nombre_emisor": "MOLINA ROMERO JOSE MIGUEL", "moneda": "SOLES", "renta_bruta": bruta,
        "retencion": 0.0, "renta_neta": bruta, "pendiente_pago": 0.0,
    }


def test_extraer_rxh_recibidos():
    html = _pagina(
        _fila_html("06/10/2026", "E001-94", "NO ANULADO", "10765113151", "MOLINA ROMERO JOSE MIGUEL   ", "1,000.00"),
        _fila_html("23/10/2026", "E001-28", "ANULADO", "10084919115", "ENCARNACION DOMINGUEZ CLEDI", "2,000.00", "160.00"),
        total=12,
    )
    pagina = extraer_rxh_recibidos(html)
    assert pagina["total"] == 12 and pagina["hasta"] == 2 and pagina["pagina_siguiente"] == "1"
    primero, segundo = pagina["filas"]
    assert primero == {
        "fecha_emision": "2026-10-06", "tipo": "RH", "numero": "E001-94", "estado": "NO ANULADO",
        "doc_emisor": "10765113151", "nombre_emisor": "MOLINA ROMERO JOSE MIGUEL", "moneda": "SOLES",
        "renta_bruta": 1000.0, "retencion": 0.0, "renta_neta": 1000.0, "pendiente_pago": 0.0,
    }
    assert (segundo["estado"], segundo["renta_bruta"], segundo["retencion"]) == ("ANULADO", 2000.0, 160.0)

    vacia = extraer_rxh_recibidos(_pagina())
    assert vacia["filas"] == [] and vacia["total"] == 0
    assert extraer_rxh_recibidos("<html>Sesion expirada</html>") is None


def test_periodo_a_revisar_y_rango():
    assert periodo_rxh_a_revisar(date(2026, 11, 5)) == "2026-10"
    assert periodo_rxh_a_revisar(date(2027, 1, 20)) == "2026-12"
    assert rango_del_periodo("2026-12") == (date(2026, 12, 1), date(2026, 12, 31))
    assert rango_del_periodo("2028-02") == (date(2028, 2, 1), date(2028, 2, 29))


def test_recibos_vigentes_crean_la_obligacion_y_los_anulados_no(db_session):
    from tests.test_deudas import _empresa, _tenant

    tenant = _tenant(db_session)
    con_rxh = _empresa(db_session, tenant, ruc="20100000011")
    solo_anulados = _empresa(db_session, tenant, ruc="20100000012")
    hoy = date.today()
    periodo = periodo_rxh_a_revisar(hoy)
    ahora = datetime.now(timezone.utc)

    assert aplicar_lectura_rxh(db_session, con_rxh.id, periodo, [_recibo("E001-94"), _recibo("E001-95"), _recibo("E001-94")], ahora) == 2
    aplicar_lectura_rxh(db_session, solo_anulados.id, periodo, [_recibo("E001-1", estado="ANULADO")], ahora)
    db_session.commit()
    assert plame_desde(db_session, [con_rxh.id, solo_anulados.id]) == {con_rxh.id: periodo, solo_anulados.id: None}

    assert revisar_obligacion_plame(db_session, con_rxh.id) == "creada"
    assert revisar_obligacion_plame(db_session, solo_anulados.id) is None
    db_session.commit()
    ob = db_session.query(EmpresaObligacion).filter(EmpresaObligacion.empresa_id == con_rxh.id).one()
    assert (ob.tipo, ob.nombre, ob.regla_vencimiento, ob.activa) == ("planilla", NOMBRE_PLAME_POR_RXH, "cronograma_sunat", True)

    # Una nueva lectura del periodo deja exactamente lo que lista SUNAT.
    aplicar_lectura_rxh(db_session, con_rxh.id, periodo, [_recibo("E001-95", estado="REVERTIDO")], ahora)
    db_session.commit()
    assert [(r.numero, r.estado) for r in db_session.query(ReciboHonorario).filter(ReciboHonorario.empresa_id == con_rxh.id)] == [
        ("E001-95", "REVERTIDO")
    ]
    # Ya no tiene recibos vigentes, pero la obligacion creada sigue: siempre.
    assert plame_desde(db_session, [con_rxh.id]) == {con_rxh.id: "0000-00"}


def test_cuadro_y_tarjeta_muestran_la_plame_por_recibos(client, db_session):
    from tests.test_deudas import _crear_empresa, _registrar

    headers = _registrar(client)
    con_rxh = _crear_empresa(client, headers, "20111111111")
    sin_rxh = _crear_empresa(client, headers, "20222222222")
    aplicar_lectura_rxh(db_session, con_rxh, "2026-10", [_recibo("E001-94"), _recibo("E001-95", bruta=500.0)], datetime.now(timezone.utc))
    db_session.commit()

    filas = {f["empresa_id"]: f for f in client.get("/cumplimiento/declaraciones?anio=2026", headers=headers).json()["filas"]}
    assert filas[con_rxh]["obligado_desde"]["0601"] == "2026-10"
    assert filas[con_rxh]["rxh"] == {"2026-10": {"cantidad": 2, "renta_bruta": 1500.0, "retencion": 0.0}}
    assert filas[sin_rxh]["obligado_desde"]["0601"] is None and filas[sin_rxh]["rxh"] == {}

    tarjetas = {e["id"]: e for e in client.get("/empresas", headers=headers).json()}
    assert tarjetas[con_rxh]["obligada_plame"] is True
    assert tarjetas[sin_rxh]["obligada_plame"] is False

    recibos = client.get(f"/empresas/{con_rxh}/rxh?periodo=2026-10", headers=headers).json()
    assert [r["numero"] for r in recibos] == ["E001-94", "E001-95"]

    # "No esta obligada" a mano gana sobre los recibos.
    client.post(f"/empresas/{con_rxh}/declaraciones/control", json={"formulario": "0601", "controlar": True}, headers=headers)
    client.post(f"/empresas/{con_rxh}/declaraciones/control", json={"formulario": "0601", "controlar": False}, headers=headers)
    assert next(e for e in client.get("/empresas", headers=headers).json() if e["id"] == con_rxh)["obligada_plame"] is False


def test_consultar_rxh_encola_el_periodo_que_vence(client, db_session, monkeypatch):
    from app.routers import declaraciones
    from tests.test_deudas import _crear_empresa, _registrar

    encolados = []
    monkeypatch.setattr(declaraciones.cola_consultas, "enqueue", lambda f, job_id, **kw: encolados.append(job_id))
    # Al crear la empresa ya se consulto su buzon: el limite por RUC no es lo que se prueba aca.
    monkeypatch.setattr(declaraciones, "verificar_limite_ruc", lambda ruc: None)
    headers = _registrar(client)
    empresa_id = _crear_empresa(client, headers, "20111111111")

    r = client.post(f"/empresas/{empresa_id}/rxh/consultar", headers=headers)
    assert r.status_code == 202, r.text
    # (la cola es la misma del buzon: al crear la empresa ya se encolo su primera consulta)
    assert r.json()["periodo"] == periodo_rxh_a_revisar(date.today()) and encolados[-1] == r.json()["id"]
    # Con una lectura en curso devuelve la misma.
    assert client.post(f"/empresas/{empresa_id}/rxh/consultar", json={"periodo": "2026-09"}, headers=headers).json()["id"] == r.json()["id"]


def test_revision_semanal_solo_empresas_sin_plame(db_session, monkeypatch):
    from app import scheduler_job
    from app.models import CredencialSol
    from tests.test_deudas import _empresa, _tenant

    tenant = _tenant(db_session)
    sin_plame = _empresa(db_session, tenant, ruc="20100000011")
    con_plame = _empresa(db_session, tenant, ruc="20100000012")
    for e in (sin_plame, con_plame):
        e.activo = True
        db_session.add(CredencialSol(empresa_id=e.id, usuario_sol="x", clave_cifrada=b"x"))
    db_session.add(EmpresaObligacion(empresa_id=con_plame.id, tipo="planilla", nombre="PLAME", regla_vencimiento="cronograma_sunat", activa=True))
    db_session.commit()

    monkeypatch.setattr(scheduler_job, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    encolados = []
    monkeypatch.setattr(scheduler_job, "encolar_lecturas", lambda db, empresas, modelo, f, **kw: encolados.append((empresas, kw)) or {"empresas_encoladas": len(empresas)})

    r = scheduler_job.encolar_rxh_semanal(hoy=date(2026, 11, 7))
    assert r == {"empresas_encoladas": 1, "periodo": "2026-10"}
    (empresas, kw), = encolados
    assert [e.id for e in empresas] == [sin_plame.id] and kw["datos_job"] == {"periodo": "2026-10"}
    assert ConsultaRxhJob.__tablename__ == "consulta_rxh_jobs"
