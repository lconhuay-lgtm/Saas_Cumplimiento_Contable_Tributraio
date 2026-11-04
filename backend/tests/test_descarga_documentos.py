"""Espera de descargas del Buzon: el listado de la carpeta se toma ANTES del clic."""
from descarga_documentos import DescargaDocumentosMixin


class _Navegador(DescargaDocumentosMixin):
    def __init__(self, carpeta):
        self.download_dir = str(carpeta)


def test_descarga_reconocida_aunque_el_pdf_aparezca_antes_de_esperar(tmp_path):
    # Chrome ya dejo el PDF (con el nombre final) cuando arranca la espera:
    # con el listado de ANTES del clic igual cuenta como descarga nueva.
    antes = set()
    (tmp_path / "rmgen_181-002-0005140.pdf").write_bytes(b"%PDF-1.4 contenido")
    assert _Navegador(tmp_path)._esperar_descarga(timeout=3, archivos_iniciales=antes) is True


def test_sin_listado_previo_el_pdf_ya_presente_no_cuenta(tmp_path):
    (tmp_path / "rmgen_181-002-0005140.pdf").write_bytes(b"%PDF-1.4 contenido")
    assert _Navegador(tmp_path)._esperar_descarga(timeout=2) is False


def test_pdf_vacio_de_chrome_no_es_descarga_completa(tmp_path):
    # El archivo vacio con el nombre final que Chrome crea al empezar.
    (tmp_path / "rmgen_181-002-0005141.pdf").write_bytes(b"")
    assert _Navegador(tmp_path)._esperar_descarga(timeout=2, archivos_iniciales=set()) is False


def test_pdf_repetido_en_la_misma_corrida_no_se_pega_a_otro_mensaje(tmp_path, monkeypatch):
    # Al abrir el segundo mensaje SUNAT seguia mostrando el primero y se bajo el
    # mismo documento otra vez ("(1).pdf"): no debe quedar como PDF del segundo.
    import adapter

    mensajes = [
        {"fecha": "10/09/2026", "asunto": "Resolucion Coactiva N 0300071539177", "elemento": object()},
        {"fecha": "08/09/2026", "asunto": "Resolucion Coactiva N 0300071441206", "elemento": object()},
    ]
    for m in mensajes:
        m["elemento"] = type("Fila", (), {"click": lambda self: None})()

    class Navegador:
        download_dir = str(tmp_path)
        driver = type("Driver", (), {"back": lambda self: None, "execute_script": lambda self, *a: None})()
        bajadas = 0

        def _descargar_documento_constancia(self):
            nombre = "rmgen_0300071539177.pdf" if not self.bajadas else "rmgen_0300071539177 (1).pdf"
            (tmp_path / nombre).write_bytes(b"%PDF-1.4 resolucion 0300071539177")
            self.bajadas += 1
            return True

    monkeypatch.setattr(adapter, "_escanear_mensajes", lambda navegador, limite: mensajes)
    monkeypatch.setattr(adapter, "_leer_contenido_texto_mensaje", lambda navegador: "texto de respaldo")
    monkeypatch.setattr(adapter.time, "sleep", lambda s: None)

    descargados, textos = adapter._descargar_documentos_nuevos(Navegador(), set(), 10)
    primero, segundo = (adapter.mensaje_id(m["fecha"], m["asunto"]) for m in mensajes)
    assert list(descargados) == [primero] and descargados[primero].endswith("rmgen_0300071539177.pdf")
    assert textos == {segundo: "texto de respaldo"}  # el segundo queda sin PDF, con su texto
