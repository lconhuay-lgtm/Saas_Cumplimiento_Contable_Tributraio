"""Lista del Buzon que no carga: falla de SUNAT si la empresa ya tenia notificaciones."""
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
