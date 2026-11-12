"""
Lectura del SIRE de madrugada (fallas del 05/11/2026): ticket que no termina a
tiempo, periodo sin comprobantes (cod 2244) y reintentos del parametro 3.13.
Datos ficticios.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

import app.jobs_liquidacion as jobs_liquidacion
import app.sire_api as sire_api
from app.models import LiquidacionComprobante, LiquidacionLectura, Usuario
from app.sire_api import ErrorApiSire, TicketPendiente
from tests.test_liquidacion_lecturas import AHORA, _preparar_empresa

# 2:00 a.m. de Lima del sabado 7/11/2026.
DOS_AM = datetime(2026, 11, 7, 7, 0, tzinfo=timezone.utc)


class _Respuesta:
    def __init__(self, datos, status=200):
        self._datos, self.status_code, self.content, self.text = datos, status, b"archivo", str(datos)

    def json(self):
        return self._datos


def _sire_falso(monkeypatch, registro):
    pedidos = []

    def _get(token, url, **params):
        pedidos.append(url.rsplit("/", 1)[-1])
        return _Respuesta({"registros": [registro]})

    monkeypatch.setattr(sire_api.time, "sleep", lambda s: None)
    monkeypatch.setattr(sire_api, "_get", _get)
    return pedidos


def test_ticket_terminado_sin_comprobantes_no_baja_archivo(monkeypatch):
    pedidos = _sire_falso(monkeypatch, {
        "desEstadoProceso": "Terminado", "detalleTicket": {"cntCPInformados": "0"},
        "archivoReporte": [{"nomArchivoReporte": "x.zip"}],
    })
    assert sire_api.descargar_ticket("token", "RVIE", "202611", "123") == b""
    assert pedidos == ["consultaestadotickets"]  # pedir el archivo daria 422 cod 2244
    assert sire_api.leer_archivo_propuesta(b"") == []


def test_ticket_terminado_con_comprobantes_baja_el_archivo(monkeypatch):
    pedidos = _sire_falso(monkeypatch, {
        "desEstadoProceso": "Terminado", "cntCPInformados": 5, "codProceso": "10",
        "archivoReporte": [{"nomArchivoReporte": "x.zip", "codTipoAchivoReporte": "01"}],
    })
    assert sire_api.descargar_ticket("token", "RVIE", "202611", "123") == b"archivo"
    assert pedidos == ["consultaestadotickets", "archivoreporte"]


def test_ticket_que_no_termina_queda_pendiente(monkeypatch):
    _sire_falso(monkeypatch, {"desEstadoProceso": "En proceso"})
    with pytest.raises(TicketPendiente) as e:
        sire_api.descargar_ticket("token", "RCE", "202610", "777")
    assert e.value.ticket == "777" and e.value.reintentable


def test_credenciales_rechazadas_no_se_reintentan(monkeypatch):
    monkeypatch.setattr(sire_api.requests, "post", lambda *a, **kw: _Respuesta({"error": "invalid_client"}, 401))
    with pytest.raises(ErrorApiSire) as e:
        sire_api.obtener_token("id", "secreto", "20123456789", "USUARIO", "clave")
    assert e.value.reintentable is False


def test_sire_pendiente_reusa_el_ticket_y_se_reintenta(client, db_session, monkeypatch):
    ctx = _preparar_empresa(client, db_session)
    emp = ctx["empresa_asignada_id"]
    monkeypatch.setattr(jobs_liquidacion, "SessionLocal", sessionmaker(bind=db_session.get_bind(), autoflush=False))
    monkeypatch.setattr(jobs_liquidacion, "obtener_token", lambda *a: "token")
    monkeypatch.setattr(jobs_liquidacion, "hoy_peru", lambda: date(2026, 11, 7))
    monkeypatch.setattr(jobs_liquidacion, "_ahora_utc", lambda: DOS_AM)
    turnos, encoladas, pedidos = [], [], []
    monkeypatch.setattr(jobs_liquidacion, "_esperar_turno_sire", lambda: turnos.append(1))
    monkeypatch.setattr(jobs_liquidacion, "encolar_lecturas",
                        lambda lecturas, espera=None: encoladas.append(([l.fuente for l in lecturas], espera)))

    def _propuesta(token, libro, periodo, ticket=None):
        pedidos.append((libro, ticket))
        if libro == "RCE" and ticket is None:
            raise TicketPendiente("El SIRE no terminó de generar la propuesta", "T-RCE")
        return []

    monkeypatch.setattr(jobs_liquidacion, "descargar_propuesta", _propuesta)

    (lectura,) = jobs_liquidacion.crear_lecturas(db_session, emp, None, "2026-11", ["sire"])
    db_session.commit()
    jobs_liquidacion.ejecutar_lecturas_liquidacion([lectura.id])

    db_session.expire_all()
    assert db_session.get(LiquidacionLectura, lectura.id).estado == "error"
    assert jobs_liquidacion.ticket_guardado(emp, "RCE", "2026-11") == "T-RCE"
    # Se pide otra lectura del SIRE a los 30 minutos.
    assert encoladas == [(["sire"], timedelta(minutes=30))]
    (reintento,) = db_session.query(LiquidacionLectura).filter(LiquidacionLectura.estado == "pendiente").all()
    assert (reintento.fuente, reintento.periodo_desde, reintento.solicitado_por) == ("sire", "2026-11", None)

    # El reintento baja el ticket guardado de compras: no pide otra propuesta ni espera turno para ella.
    turnos.clear()
    jobs_liquidacion.ejecutar_lecturas_liquidacion([reintento.id])
    db_session.expire_all()
    assert db_session.get(LiquidacionLectura, reintento.id).estado == "completado"
    assert pedidos[-2:] == [("RVIE", None), ("RCE", "T-RCE")]
    assert turnos == [1]
    assert jobs_liquidacion.ticket_guardado(emp, "RCE", "2026-11") is None
    assert len(encoladas) == 1  # lo que salio bien no se reintenta


def test_reintentos_hasta_3_veces_y_hasta_las_7(client, db_session, monkeypatch):
    ctx = _preparar_empresa(client, db_session)
    emp = ctx["empresa_asignada_id"]
    usuario = db_session.query(Usuario).first().id
    encoladas = []
    monkeypatch.setattr(jobs_liquidacion, "encolar_lecturas", lambda lecturas, espera=None: encoladas.append(lecturas))

    def fallida(fuente="sire", solicitado_por=None):
        l = LiquidacionLectura(
            empresa_id=emp, solicitado_por=solicitado_por, fuente=fuente, periodo_desde="2026-11",
            periodo_hasta="2026-11", estado="error", creado_en=DOS_AM - timedelta(minutes=5),
        )
        db_session.add(l)
        db_session.commit()
        return l

    def reintentar(lecturas, ahora=DOS_AM):
        nuevas = jobs_liquidacion.programar_reintentos(db_session, lecturas, ahora)
        for n in nuevas:  # se cuentan como intentos de esa madrugada
            n.estado, n.creado_en = "error", DOS_AM
        db_session.commit()
        return sorted(n.fuente for n in nuevas)

    sire, aduanas = fallida(), fallida("aduanas")
    assert reintentar([sire, aduanas]) == ["aduanas", "sire"]  # un solo trabajo con las dos
    assert len(encoladas) == 1
    assert reintentar([sire]) == ["sire"]
    assert reintentar([sire]) == ["sire"]
    assert reintentar([sire]) == []  # ya van 1 + 3 intentos hoy
    assert reintentar([aduanas]) == ["aduanas"]  # Aduanas lleva solo 2

    # Pasadas las 6:30 a.m. el reintento caeria despues de las 7:00: no se pide.
    assert reintentar([fallida("aduanas")], ahora=datetime(2026, 11, 7, 11, 45, tzinfo=timezone.utc)) == []
    # Lo pedido a mano y el Menu SOL no se reintentan solos.
    assert reintentar([fallida(solicitado_por=usuario)], ahora=datetime(2026, 11, 8, 7, 0, tzinfo=timezone.utc)) == []
    assert reintentar([fallida("retenciones")], ahora=datetime(2026, 11, 8, 7, 0, tzinfo=timezone.utc)) == []


def test_sire_sin_comprobantes_no_borra_lo_leido(client, db_session, monkeypatch):
    ctx = _preparar_empresa(client, db_session)
    emp = ctx["empresa_asignada_id"]
    jobs_liquidacion.aplicar_comprobantes(db_session, emp, "RCE", "2026-10", [{
        "car_sunat": "RCE-1", "periodo": "2026-10", "fecha_emision": "2026-10-01", "tipo_comprobante": "01",
        "serie": "F001", "numero": "1", "doc_contraparte": "", "nombre_contraparte": "", "base_gravada": 100.0,
        "igv": 18.0, "descuento_base": 0.0, "descuento_igv": 0.0, "base_dgng": 0.0, "igv_dgng": 0.0,
        "no_gravado": 0.0, "exportacion": 0.0, "total": 118.0, "moneda": "PEN", "detraccion": "", "dam": "", "datos": {},
    }], AHORA)
    db_session.commit()
    monkeypatch.setattr(jobs_liquidacion, "_esperar_turno_sire", lambda: None)
    monkeypatch.setattr(jobs_liquidacion, "descargar_propuesta", lambda token, libro, periodo, ticket=None: [])

    with pytest.raises(ErrorApiSire) as e:
        jobs_liquidacion.leer_propuesta(db_session, emp, "token", "RCE", "2026-10")
    assert e.value.reintentable is False and "se conservan" in str(e.value)
    assert db_session.query(LiquidacionComprobante).count() == 1
    # Si no habia nada leido, 0 comprobantes es un resultado normal (mes que recien empieza).
    assert jobs_liquidacion.leer_propuesta(db_session, emp, "token", "RVIE", "2026-10") == []
