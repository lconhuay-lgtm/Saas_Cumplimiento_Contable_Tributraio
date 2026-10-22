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


def test_busqueda_y_listado(client, db_session, monkeypatch):
    from tests.test_deudas import _crear_empresa, _registrar

    # Crear la empresa ya lanza su primera consulta del buzon y eso activa la
    # espera de 60 s por RUC: aca no se prueba ese limite.
    monkeypatch.setattr("app.routers.detracciones.verificar_limite_ruc", lambda ruc: None)
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


def test_marca_de_avance_por_tramos(db_session):
    from app.jobs import _inicio_pendiente_detracciones, registrar_tramo_detracciones
    from app.models import DetraccionCobertura
    from tests.test_deudas import _empresa, _tenant

    empresa = _empresa(db_session, _tenant(db_session))
    ahora = datetime.now(timezone.utc)
    hoy = date(2026, 10, 22)
    job = ConsultaDetraccionesJob(empresa_id=empresa.id, modo="carga_inicial", fecha_desde=date(2022, 1, 1), fecha_hasta=hoy)

    assert _inicio_pendiente_detracciones(db_session, job) == date(2022, 1, 1)
    registrar_tramo_detracciones(db_session, empresa.id, date(2022, 1, 1), date(2022, 1, 30), [normalizar_detraccion(_crudo("C1"), "pagosIndividuales")], ahora, completa_hasta=hoy)
    registrar_tramo_detracciones(db_session, empresa.id, date(2022, 1, 31), date(2022, 3, 1), [], ahora, completa_hasta=hoy)
    cobertura = db_session.get(DetraccionCobertura, empresa.id)
    assert (cobertura.desde, cobertura.hasta, cobertura.carga_completa) == (date(2022, 1, 1), date(2022, 3, 1), False)
    # Si falla a la mitad, el reintento (o la noche siguiente) sigue desde ahi.
    assert _inicio_pendiente_detracciones(db_session, job) == date(2022, 3, 2)
    # Un tramo que no empalma no mueve la marca.
    registrar_tramo_detracciones(db_session, empresa.id, date(2023, 1, 1), date(2023, 1, 30), [], ahora)
    assert db_session.get(DetraccionCobertura, empresa.id).hasta == date(2022, 3, 1)
    registrar_tramo_detracciones(db_session, empresa.id, date(2022, 3, 2), hoy, [], ahora, completa_hasta=hoy)
    assert db_session.get(DetraccionCobertura, empresa.id).carga_completa is True
    assert db_session.query(DetraccionPago).count() == 1


def test_carga_inicial_y_lectura_semanal(db_session, monkeypatch):
    import app.hora_peru as hora_peru
    import app.scheduler_job as scheduler_job
    from app.models import CredencialSol, DetraccionCobertura
    from tests.test_deudas import _empresa, _tenant

    monkeypatch.setattr(scheduler_job, "SessionLocal", lambda: db_session)
    hoy = {"valor": datetime(2026, 10, 26, 12, 0, tzinfo=hora_peru.ZONA_PERU)}
    monkeypatch.setattr(hora_peru, "ahora_peru", lambda: hoy["valor"])
    tenant = _tenant(db_session)
    con_detracciones = _empresa(db_session, tenant, ruc="20100000021")
    sin_detracciones = _empresa(db_session, tenant, ruc="20100000023")
    _empresa(db_session, tenant, ruc="20100000022")  # sin credenciales SOL: nunca se encola
    for e in (con_detracciones, sin_detracciones):
        db_session.add(CredencialSol(empresa_id=e.id, usuario_sol="X", clave_cifrada=b"x", dek_cifrada=b"x"))
    db_session.commit()
    # El encolado cierra la sesion: se guardan los ids antes.
    con_id, sin_id = con_detracciones.id, sin_detracciones.id

    # Noche 1: carga inicial de las dos con clave, desde 2022.
    assert scheduler_job.encolar_detracciones_carga_inicial()["empresas_encoladas"] == 2
    jobs = db_session.query(ConsultaDetraccionesJob).all()
    assert {(j.modo, j.fecha_desde, j.fecha_hasta, j.tipos_cuenta) for j in jobs} == {("carga_inicial", date(2022, 1, 1), date(2026, 10, 26), "1,2,3")}
    # Sin carga completa todavia, la semanal no las toma.
    db_session.query(ConsultaDetraccionesJob).update({"estado": "completado"})
    db_session.commit()
    assert scheduler_job.encolar_detracciones_semanal()["empresas_encoladas"] == 0

    for eid in (con_id, sin_id):
        db_session.add(DetraccionCobertura(empresa_id=eid, desde=date(2022, 1, 1), hasta=date(2026, 10, 20), carga_completa=True))
    db_session.add(DetraccionPago(empresa_id=con_id, num_constancia="Z1", tipo_cuenta="2"))
    db_session.commit()
    assert scheduler_job.encolar_detracciones_carga_inicial()["empresas_encoladas"] == 0

    # Lunes cualquiera: solo la que tiene depositos, desde la marca menos 7 dias, sus cuentas usadas + la convencional.
    scheduler_job.encolar_detracciones_semanal()
    semanal = db_session.query(ConsultaDetraccionesJob).filter(ConsultaDetraccionesJob.modo == "semanal").all()
    assert [(j.empresa_id, j.fecha_desde, j.tipos_cuenta) for j in semanal] == [(con_id, date(2026, 10, 13), "1,2")]

    # Primer lunes del mes: tambien la que no tiene depositos, todas las cuentas y 42 dias atras.
    db_session.query(ConsultaDetraccionesJob).update({"estado": "completado"})
    db_session.commit()
    hoy["valor"] = datetime(2026, 11, 2, 12, 0, tzinfo=hora_peru.ZONA_PERU)
    scheduler_job.encolar_detracciones_semanal()
    mensual = db_session.query(ConsultaDetraccionesJob).filter(ConsultaDetraccionesJob.fecha_hasta == date(2026, 11, 2)).all()
    assert {(j.empresa_id, j.fecha_desde, j.tipos_cuenta) for j in mensual} == {
        (con_id, date(2026, 9, 8), "1,2,3"), (sin_id, date(2026, 9, 8), "1,2,3"),
    }


def test_detracciones_de_a_una(monkeypatch):
    import app.jobs as jobs
    from app.queue_conn import redis_conn

    llamadas = []
    monkeypatch.setattr(jobs, "_ejecutar_consulta_detracciones", lambda job_id: llamadas.append(job_id))
    redis_conn.set(jobs.CLAVE_DETRACCIONES_EN_CURSO, "otro-job")
    jobs.ejecutar_consulta_detracciones("job-1")  # turno ocupado: vuelve a la cola, no corre
    assert llamadas == []
    redis_conn.delete(jobs.CLAVE_DETRACCIONES_EN_CURSO)
    jobs.ejecutar_consulta_detracciones("job-1")  # turno libre: corre y lo suelta
    assert llamadas == ["job-1"] and redis_conn.get(jobs.CLAVE_DETRACCIONES_EN_CURSO) is None
