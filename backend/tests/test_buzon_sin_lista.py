"""Lista del Buzon que no carga: falla de SUNAT si la empresa ya tenia notificaciones."""
import uuid

import adapter


class _Driver:
    def get(self, url):
        pass


class _NavegadorFalso:
    def __init__(self, empresa, headless):
        self.driver = _Driver()
        self.razon_social_detectada = "EMPRESA S.A.C."
        self.condicion_domicilio_detectada = "Habido"
        self.estado_contribuyente_detectado = None
        self.flujo_detectado = None
        self.credenciales_rechazadas = False

    def initialize_browser(self):
        return True

    def _hacer_clicks_sunat(self, empresa):
        return True

    def _navegar_a_buzon_notificaciones(self):
        return True

    def _cerrar_alerta_si_aparece(self):
        pass

    def close_browser(self):
        pass


def _consultar(monkeypatch, con_historial):
    monkeypatch.setattr(adapter, "SunatWebNavigator", _NavegadorFalso)
    monkeypatch.setattr(adapter.time, "sleep", lambda s: None)
    monkeypatch.setattr(adapter, "_esperar_lista_mensajes", lambda nav: False)
    monkeypatch.setattr(adapter, "_leer_lista_mensajes", lambda nav, limite: [])
    return adapter.consultar_buzon(
        "20494056934", "USUARIO", "clave", leer_estado_contribuyente=False,
        descargar_documentos=False, leer_buzon_mensajes=False, buzon_con_historial=con_historial,
    )


def test_lista_vacia_con_historial_es_falla_de_sunat(monkeypatch):
    resultado = _consultar(monkeypatch, con_historial=True)
    assert resultado["ok"] is False
    assert resultado["error"] == adapter.ERROR_BUZON_SIN_LISTA
    assert resultado["razon_social_sunat"] == "EMPRESA S.A.C."


def test_lista_vacia_sin_historial_es_buzon_vacio(monkeypatch):
    resultado = _consultar(monkeypatch, con_historial=False)
    assert resultado["ok"] is True
    assert resultado["mensajes"] == []


def test_el_job_reconoce_el_error_del_adapter():
    import app.jobs as jobs
    assert adapter.ERROR_BUZON_SIN_LISTA.startswith(jobs.PREFIJO_ERROR_BUZON_SIN_LISTA)


def test_reintento_unico_45_minutos_despues(db_session, monkeypatch):
    import app.jobs as jobs
    from app.models import ConsultaJob
    from app.queue_conn import cola_consultas

    encolados = []
    monkeypatch.setattr(cola_consultas, "enqueue_in", lambda espera, funcion, *args, **kw: encolados.append((espera, funcion, args)))
    empresa_id = str(uuid.uuid4())
    job_id = jobs._reintentar_buzon_sin_lista(db_session, empresa_id)

    reintento = db_session.query(ConsultaJob).filter(ConsultaJob.id == job_id).one()
    assert reintento.origen == "reintento" and reintento.estado == "pendiente"
    assert encolados == [(jobs.ESPERA_REINTENTO_BUZON_SIN_LISTA, jobs.ejecutar_consulta_buzon, (job_id,))]
