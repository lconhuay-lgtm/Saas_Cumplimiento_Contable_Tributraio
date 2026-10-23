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
