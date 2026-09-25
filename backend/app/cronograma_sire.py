"""
Cronograma de Atraso de los Registros Electronicos de SUNAT (Anexo II de
la RS 281-2022/SUNAT) -- la fecha maxima para registrar las operaciones de
un periodo en el Registro de Compras y en el Registro de Ventas e Ingresos
Electronicos (ambos comparten la misma fecha, confirmado leyendo la
pagina real). Es una obligacion DISTINTA de la declaracion mensual de
IGV-Renta/PLAME que ya cubre cronograma_sunat.py -- misma agrupacion por
ultimo digito de RUC, pero con fechas mas tardias (unas semanas despues
del cierre del mes de operaciones).

Al igual que el cronograma de Obligaciones Mensuales, esta pagina es
publica, estatica, y NO requiere sesion ni Selenium -- un simple GET +
parseo de texto. Este modulo solo se encarga de descargar/parsear/guardar
la tabla SIRE -- la agrupacion por RUC (grupo_para_empresa) y las
consultas de agenda/proximos vencimientos siguen viviendo en
cronograma_sunat.py, ahora parametrizadas con tipo="mensual"|"sire" (una
sola fuente de verdad para esa regla, que es la misma norma legal en
ambos casos) en vez de duplicarlas aca.

URL confirmada (verificada el 25/09/2026, trae los 12 periodos de 2026
con la estructura esperada):
  https://www.sunat.gob.pe/orientacion/cronogramas/cronoRegistroC-V-{anio}.html

Estructura de la tabla (confirmada leyendo la pagina real): titulo
"CRONOGRAMA DE ATRASO DE LOS REGISTROS ELECTRONICOS", una fila por periodo
("Ene-2026", "Feb-2026", ...) y 7 columnas de fecha maxima de atraso segun
el ultimo digito del RUC -- MISMO orden de columnas que el cronograma
mensual. A diferencia de esa pagina, aca cada celda SIEMPRE trae el anio
explicito mas la fecha (formato "13-Feb-26", dia-mes-anio de 2 digitos),
asi que no hace falta inferir el anio del periodo.
"""
import logging
import re
from datetime import date, datetime, timezone

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.models import CronogramaVencimiento
from app.cronograma_sunat import GRUPOS_COLUMNAS, MESES_ES, MESES_PATRON, parsear_periodo

logger = logging.getLogger("app.cronograma_sire")

URL_CRONOGRAMA_SIRE_TEMPLATE = "https://www.sunat.gob.pe/orientacion/cronogramas/cronoRegistroC-V-{anio}.html"

# "13-Feb-26" -- dia, mes abreviado y anio de 2 digitos, siempre los 3
# separados por guion (a diferencia del cronograma mensual, que a veces
# separa con espacio y casi nunca trae el anio). El anio de 2 digitos
# siempre esta presente aca, asi que no hace falta inferirlo del periodo.
# OJO (confirmado leyendo la pagina real): el espaciado alrededor del
# SEGUNDO guion es inconsistente -- la mayoria de las celdas traen
# "14-Jul-26" pero varias traen "14-Jul- 26" (espacio antes del anio,
# probablemente por como quedan separados los nodos de texto en el HTML
# de origen) -- el patron tolera espacio opcional alrededor de ambos
# guiones para no perder esas filas.
_RE_TOKEN_SIRE = re.compile(
    rf"(?P<fecha>\d{{1,2}}\s*-\s*(?:{MESES_PATRON})\s*-\s*\d{{2}})"
    rf"|(?P<periodo>(?:{MESES_PATRON})[.\-]?\s*-?\s*\d{{4}})",
    re.UNICODE,
)
_RE_CELDA_FECHA_SIRE = re.compile(r"(\d{1,2})\s*-\s*([A-Za-zÁÉÍÓÚÑáéíóúñ]{3,})\s*-\s*(\d{2})", re.UNICODE)


def _parsear_fecha_celda_sire(texto: str) -> date | None:
    """"13-Feb-26" -> date(2026, 2, 13). El anio de 2 digitos siempre viene
    presente en esta pagina -- se expande sumando 2000 (no hace falta
    logica de siglo, el sistema no maneja fechas de otro siglo)."""
    texto = " ".join(texto.split())
    m = _RE_CELDA_FECHA_SIRE.search(texto)
    if not m:
        return None
    dia_str, mes_str, anio2_str = m.groups()
    mes_num = MESES_ES.get(mes_str.strip().lower()[:3])
    if not mes_num:
        return None
    anio = 2000 + int(anio2_str)
    try:
        return date(anio, mes_num, int(dia_str))
    except ValueError:
        return None


def descargar_html_cronograma_sire(anio: int) -> str:
    url = URL_CRONOGRAMA_SIRE_TEMPLATE.format(anio=anio)
    resp = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"},
    )
    resp.raise_for_status()
    return resp.text


def parsear_cronograma_sire_html(html: str, anio_esperado: int) -> list[dict]:
    """
    Devuelve una lista de {"periodo_tributario", "grupo", "fecha_vencimiento"}
    -- 12 periodos x 7 grupos = 84 filas en un ejercicio normal. Mismo
    enfoque que parsear_cronograma_html (cronograma_sunat.py): recorre el
    TEXTO PLANO de la pagina en orden de lectura, sin depender de que sea
    un <table> HTML -- ver el docstring de esa funcion para el porque.
    """
    soup = BeautifulSoup(html, "html.parser")
    texto_completo = " ".join(soup.get_text(" ", strip=True).split())

    marca_inicio = re.search(r"CRONOGRAMA\s+DE\s+ATRASO", texto_completo, re.IGNORECASE)
    marca_fin = re.search(r"BASE\s+LEGAL", texto_completo, re.IGNORECASE)
    inicio = marca_inicio.start() if marca_inicio else 0
    fin = marca_fin.start() if marca_fin else len(texto_completo)
    texto_relevante = texto_completo[inicio:fin]

    filas_resultado: list[dict] = []
    periodo_actual: str | None = None
    fechas_del_periodo_actual = 0

    for m in _RE_TOKEN_SIRE.finditer(texto_relevante):
        if m.group("periodo"):
            if periodo_actual is not None and fechas_del_periodo_actual < len(GRUPOS_COLUMNAS):
                logger.warning(
                    f"Cronograma SIRE {anio_esperado}: el periodo {periodo_actual} solo trajo "
                    f"{fechas_del_periodo_actual}/{len(GRUPOS_COLUMNAS)} fechas antes del siguiente periodo."
                )
            periodo_info = parsear_periodo(m.group("periodo"))
            if not periodo_info:
                continue
            periodo_actual, _ = periodo_info
            fechas_del_periodo_actual = 0
        elif m.group("fecha"):
            if periodo_actual is None or fechas_del_periodo_actual >= len(GRUPOS_COLUMNAS):
                continue
            fecha = _parsear_fecha_celda_sire(m.group("fecha"))
            if fecha is None:
                continue
            grupo = GRUPOS_COLUMNAS[fechas_del_periodo_actual]
            filas_resultado.append({
                "periodo_tributario": periodo_actual,
                "grupo": grupo,
                "fecha_vencimiento": fecha,
            })
            fechas_del_periodo_actual += 1

    minimo_esperado = int(12 * 7 * 0.5)
    if len(filas_resultado) < minimo_esperado:
        raise ValueError(
            f"El cronograma SIRE {anio_esperado} se parseo con muy pocas filas ({len(filas_resultado)}) -- "
            "revisar si SUNAT cambio el formato de esta pagina."
        )

    return filas_resultado


def sincronizar_cronograma_sire(db: Session, anio: int) -> dict:
    """Descarga, parsea y guarda (upsert, tipo="sire") el cronograma SIRE de un ejercicio."""
    html = descargar_html_cronograma_sire(anio)
    filas = parsear_cronograma_sire_html(html, anio)

    guardadas = 0
    for fila in filas:
        existente = (
            db.query(CronogramaVencimiento)
            .filter(
                CronogramaVencimiento.periodo_tributario == fila["periodo_tributario"],
                CronogramaVencimiento.grupo == fila["grupo"],
                CronogramaVencimiento.tipo == "sire",
            )
            .first()
        )
        fecha_dt = datetime.combine(fila["fecha_vencimiento"], datetime.min.time(), tzinfo=timezone.utc)
        if existente:
            existente.fecha_vencimiento = fecha_dt
        else:
            db.add(CronogramaVencimiento(
                periodo_tributario=fila["periodo_tributario"],
                grupo=fila["grupo"],
                tipo="sire",
                fecha_vencimiento=fecha_dt,
            ))
        guardadas += 1
    db.commit()

    periodos = sorted({f["periodo_tributario"] for f in filas})
    logger.info(
        f"Cronograma SIRE {anio} sincronizado: {guardadas} fila(s), "
        f"periodos {periodos[0] if periodos else '?'}..{periodos[-1] if periodos else '?'}"
    )
    return {"anio": anio, "periodos_procesados": len(periodos), "filas_guardadas": guardadas}


def asegurar_cronograma_sire_vigente(db: Session) -> dict:
    """Mismo patron idempotente que asegurar_cronograma_vigente() (cronograma_sunat.py) -- ver ese docstring."""
    hoy = datetime.now(timezone.utc)
    anios_a_revisar = [hoy.year]
    if hoy.month == 12:
        anios_a_revisar.append(hoy.year + 1)

    resultados = []
    for anio in anios_a_revisar:
        periodos_existentes = (
            db.query(CronogramaVencimiento.periodo_tributario)
            .filter(
                CronogramaVencimiento.periodo_tributario.like(f"{anio}-%"),
                CronogramaVencimiento.tipo == "sire",
            )
            .distinct()
            .count()
        )
        if periodos_existentes >= 12:
            continue
        try:
            resultado = sincronizar_cronograma_sire(db, anio)
            resultados.append(resultado)
        except Exception as e:
            logger.warning(f"No se pudo sincronizar el cronograma SIRE {anio} automaticamente: {e}")

    return {"anios_sincronizados": resultados}
