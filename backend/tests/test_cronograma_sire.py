"""
Parseo y sincronizacion del cronograma SIRE (Atraso de Registros
Electronicos) -- ver backend/app/cronograma_sire.py. Mismo enfoque de
fixture que se hubiera usado para cronograma_sunat.py: un HTML minimo que
reproduce la estructura REAL confirmada a mano el 25/09/2026 (titulo,
encabezado con "0,1,2,...9" de relleno, un par de filas de datos con el
formato "13-Feb-26", y el pie con "Base Legal").
"""
from app.cronograma_sire import parsear_cronograma_sire_html, sincronizar_cronograma_sire
from app.models import CronogramaVencimiento

_MESES_PERIODO = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Set", "Oct", "Nov", "Dic"]
_MESES_VENCIMIENTO = ["Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Set", "Oct", "Nov", "Dic", "Ene"]

# 12 periodos x 7 grupos, mismo formato real confirmado a mano el
# 25/09/2026 (titulo, encabezado con "0,1,2,...9" de relleno que NO debe
# confundirse con datos, filas "13-Feb-26", pie con "Base Legal").
_FILAS_HTML = []
for i, mes_periodo in enumerate(_MESES_PERIODO):
    mes_vencimiento = _MESES_VENCIMIENTO[i]
    anio_vencimiento = "27" if mes_vencimiento == "Ene" else "26"
    _FILAS_HTML.append(f"<div>{mes_periodo}-2026</div>")
    for dia in (13, 16, 17, 18, 19, 20, 23):
        _FILAS_HTML.append(f"<div>{dia}-{mes_vencimiento}-{anio_vencimiento}</div>")

HTML_SIRE_FIXTURE = f"""
<html><body>
<h2>CRONOGRAMA DE ATRASO DE LOS REGISTROS ELECTRÓNICOS</h2>
<div>MES AL QUE CORRESPONDE LA OBLIGACIÓN (*)</div>
<div>MÁXIMO ATRASO PERMITIDO SEGÚN EL ÚLTIMO DÍGITO DEL RUC</div>
<div>0</div><div>1</div><div>2 y 3</div><div>4 y 5</div><div>6 y 7</div><div>8 y 9</div>
<div>BUENOS CONTRIBUYENTES y UESP</div>
<div>0, 1 , 2, 3, 4, 5, 6, 7, 8 y 9</div>
{"".join(_FILAS_HTML)}
<div>Nota: en cada casilla se indica...</div>
<div>Base Legal: Anexo II - Resolucion de Superintendencia N 281-2022/SUNAT</div>
</body></html>
"""


def test_parsea_periodo_y_fecha_con_anio_de_2_digitos():
    filas = parsear_cronograma_sire_html(HTML_SIRE_FIXTURE, 2026)
    assert len(filas) == 84  # 12 periodos x 7 grupos

    ene = [f for f in filas if f["periodo_tributario"] == "2026-01"]
    assert len(ene) == 7
    por_grupo = {f["grupo"]: f["fecha_vencimiento"] for f in ene}
    assert por_grupo["0"].isoformat() == "2026-02-13"
    assert por_grupo["8_9"].isoformat() == "2026-02-20"
    assert por_grupo["buenos_contribuyentes"].isoformat() == "2026-02-23"

    # Diciembre-2026 vence en enero-2027 -- el anio de 2 digitos debe
    # resolverse al ejercicio siguiente, no quedarse en 2026.
    dic = [f for f in filas if f["periodo_tributario"] == "2026-12"]
    assert dic[0]["fecha_vencimiento"].isoformat() == "2027-01-13"


def test_no_confunde_el_relleno_de_digitos_del_encabezado_con_datos():
    filas = parsear_cronograma_sire_html(HTML_SIRE_FIXTURE, 2026)
    # El "0, 1, 2, 3, 4, 5, 6, 7, 8 y 9" del encabezado no debe generar
    # filas -- ni el patron de fecha ("13-Feb-26") ni el de periodo
    # ("Ene-2026") le calzan.
    periodos_validos = {f"2026-{m:02d}" for m in range(1, 13)}
    assert all(f["periodo_tributario"] in periodos_validos for f in filas)


def test_sincronizar_cronograma_sire_guarda_con_tipo_sire(db_session, monkeypatch):
    monkeypatch.setattr("app.cronograma_sire.descargar_html_cronograma_sire", lambda anio: HTML_SIRE_FIXTURE)

    resultado = sincronizar_cronograma_sire(db_session, 2026)
    assert resultado["filas_guardadas"] == 84
    assert resultado["periodos_procesados"] == 12

    filas = db_session.query(CronogramaVencimiento).filter(CronogramaVencimiento.tipo == "sire").all()
    assert len(filas) == 84
    assert all(f.tipo == "sire" for f in filas)


def test_tolera_espacio_antes_del_anio_de_2_digitos():
    """
    Regresion de un caso real: al sincronizar contra la pagina REAL de
    SUNAT el 25/09/2026, los periodos de junio y agosto trajeron solo
    1/7 fechas -- la causa era que varias celdas del HTML original traen
    un espacio antes del anio ("14-Jul-26" -> "14-Jul- 26" en la pagina
    real, probablemente por como separa BeautifulSoup nodos de texto
    contiguos en esa seccion puntual). El parser debe tolerar ese espacio
    igual que el caso normal, sin perder filas.
    """
    # El periodo Jun-2026 vence en Jul-2026 (dia 13 = grupo "0", ver bucle
    # de _FILAS_HTML arriba); se le inserta el espacio raro antes del
    # anio para reproducir el caso real.
    html_con_espacios = HTML_SIRE_FIXTURE.replace("13-Jul-26", "13-Jul- 26")
    filas = parsear_cronograma_sire_html(html_con_espacios, 2026)
    assert len(filas) == 84

    jun = {f["grupo"]: f["fecha_vencimiento"] for f in filas if f["periodo_tributario"] == "2026-06"}
    assert jun["0"].isoformat() == "2026-07-13"


def test_muy_pocas_filas_lanza_error():
    html_incompleto = "<html><body>CRONOGRAMA DE ATRASO Ene-2026 13-Feb-26 BASE LEGAL</body></html>"
    try:
        parsear_cronograma_sire_html(html_incompleto, 2026)
        assert False, "deberia haber lanzado ValueError"
    except ValueError:
        pass
