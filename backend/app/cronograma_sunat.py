"""
Cronograma de Obligaciones Tributarias Mensuales de SUNAT (RS 281-2022,
vigente de forma permanente desde el ejercicio 2023). A diferencia de todo
lo demas que scrapeamos de SUNAT, esta pagina es publica, estatica y NO
requiere sesion ni Selenium -- es un simple GET + parseo de HTML, la misma
tabla sirve tanto para la declaracion mensual de IGV-Renta (PDT/F.621) como
para PLAME (F.601), asi que no hace falta un cronograma separado por tipo
de obligacion.

URL confirmada (verificada a mano el 18/09/2026, trae los 12 periodos de
2026 con la estructura esperada):
  https://www.sunat.gob.pe/orientacion/cronogramas/{anio}/cObligacionMensual{anio}.html

Estructura de la tabla (confirmada leyendo la pagina real): una fila por
periodo tributario ("Ene-2026", "Feb-2026", ...) y 7 columnas de fecha de
vencimiento segun el ultimo digito del RUC: "0", "1", "2 y 3", "4 y 5",
"6 y 7", "8 y 9", y "BUENOS CONTRIBUYENTES y UESP" (fecha extendida). Cada
celda de fecha trae el dia y el mes ("16 Feb"); solo la fila de diciembre
incluye el anio explicito en sus celdas ("19 Ene 2027"), porque es el unico
caso donde el vencimiento cae en el ejercicio siguiente.
"""
import logging
import re
from datetime import date, datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import CronogramaVencimiento, Empresa

logger = logging.getLogger("app.cronograma_sunat")

URL_CRONOGRAMA_TEMPLATE = "https://www.sunat.gob.pe/orientacion/cronogramas/{anio}/cObligacionMensual{anio}.html"

# Orden EXACTO de las columnas de la tabla oficial (confirmado leyendo la
# pagina real): "0 | 1 | 2 y 3 | 4 y 5 | 6 y 7 | 8 y 9 | BUENOS
# CONTRIBUYENTES y UESP". Fijo a proposito -- la estructura viene de la
# Resolucion de Superintendencia (norma legal), mucho mas estable que
# cualquier detalle de maquetado HTML de la pagina.
GRUPOS_COLUMNAS = ["0", "1", "2_3", "4_5", "6_7", "8_9", "buenos_contribuyentes"]

_MESES_ES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}

# "16 Feb" o "19 Ene 2027" (el anio solo aparece cuando el vencimiento cae
# en el ejercicio siguiente al del periodo declarado -- ver Dic-2026 en la
# pagina real).
_RE_CELDA_FECHA = re.compile(r"(\d{1,2})\s*[.\-]?\s*([A-Za-zÁÉÍÓÚÑáéíóúñ]{3,})\.?\s*(\d{4})?", re.UNICODE)
# "Ene-2026" -> grupo 1 = mes, grupo 2 = anio.
_RE_PERIODO = re.compile(r"([A-Za-zÁÉÍÓÚÑáéíóúñ]{3,})[.\-]?\s*[-\s]\s*(\d{4})", re.UNICODE)

_MESES_PATRON = "Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|Set|Sep|Oct|Nov|Dic"

# Token combinado para el escaneo secuencial del texto plano de la pagina
# (ver parsear_cronograma_html) -- "fecha" va primero en la alternancia a
# proposito: como una celda de fecha SIEMPRE empieza con un digito
# ("18 Ene 2027") y un periodo SIEMPRE empieza con una letra ("Ene-2026"),
# poner "fecha" primero evita que "Ene 2027" (parte de una celda con anio
# explicito) se confunda con un periodo nuevo.
_RE_TOKEN = re.compile(
    rf"(?P<fecha>\d{{1,2}}\s*[.\-]?\s*(?:{_MESES_PATRON})\.?\s*(?:\d{{4}})?)"
    rf"|(?P<periodo>(?:{_MESES_PATRON})[.\-]?\s*-?\s*\d{{4}})",
    re.UNICODE,
)


def _parsear_fecha_celda(texto: str, anio_periodo: int) -> date | None:
    """
    Convierte el texto de una celda de vencimiento en un date real. Si la
    celda no trae anio explicito se usa el anio del periodo -- SUNAT solo
    escribe el anio cuando el vencimiento cae en el ejercicio siguiente, asi
    que confiar en el anio explicito cuando esta presente resuelve el cruce
    de anio sin tener que inferir nada por orden calendario.
    """
    texto = " ".join(texto.split())
    m = _RE_CELDA_FECHA.search(texto)
    if not m:
        return None
    dia_str, mes_str, anio_str = m.groups()
    mes_num = _MESES_ES.get(mes_str.strip().lower()[:3])
    if not mes_num:
        return None
    anio = int(anio_str) if anio_str else anio_periodo
    try:
        return date(anio, mes_num, int(dia_str))
    except ValueError:
        return None


def _parsear_periodo(texto: str) -> tuple[str, int] | None:
    """'Ene-2026' -> ('2026-01', 2026). None si el texto no calza (p.ej. es un encabezado)."""
    texto = " ".join(texto.split())
    m = _RE_PERIODO.search(texto)
    if not m:
        return None
    mes_str, anio_str = m.groups()
    mes_num = _MESES_ES.get(mes_str.strip().lower()[:3])
    if not mes_num:
        return None
    anio = int(anio_str)
    return f"{anio:04d}-{mes_num:02d}", anio


def descargar_html_cronograma(anio: int) -> str:
    url = URL_CRONOGRAMA_TEMPLATE.format(anio=anio)
    resp = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"},
    )
    resp.raise_for_status()
    return resp.text


def parsear_cronograma_html(html: str, anio_esperado: int) -> list[dict]:
    """
    Devuelve una lista de {"periodo_tributario", "grupo", "fecha_vencimiento"}
    -- 12 periodos x 7 grupos = 84 filas en un ejercicio normal.

    IMPORTANTE (version 2, corregida tras un fallo real en produccion): la
    version anterior buscaba un <table> HTML con "PERIODO TRIBUTARIO" en el
    encabezado -- fallo porque la pagina REAL de SUNAT no arma esta seccion
    con un <table> (se confirmo con el error real: "No se encontro la
    tabla del cronograma"). Esta version NO depende para nada del tipo de
    markup (tabla, divs, grid, lo que sea): recorre el TEXTO PLANO de la
    pagina en orden de lectura (que BeautifulSoup preserva sin importar el
    tag usado) y reconoce la secuencia "periodo, seguido de hasta 7
    fechas" -- el mismo patron que seguiria una persona leyendo la tabla en
    voz alta, sin importar como este maquetada por dentro.
    """
    soup = BeautifulSoup(html, "html.parser")

    # separador " " entre nodos de texto para que celdas contiguas en el
    # DOM (p.ej. dos <td> o dos <div> seguidos) no queden pegadas sin
    # espacio -- despues se colapsa todo a espacios simples.
    texto_completo = " ".join(soup.get_text(" ", strip=True).split())

    # Recorta al tramo relevante si se pueden ubicar las anclas conocidas
    # del contenido oficial -- reduce el riesgo de que un numero de otra
    # parte de la pagina (p.ej. "Oficio N°0385-2026-EF" en la nota de UESP,
    # que viene DESPUES de "Base Legal") se confunda con una fecha. Si no
    # se encuentran las anclas (por si el texto cambia de redaccion), se
    # sigue con la pagina completa -- la especificidad de los patrones ya
    # filtra casi todo el ruido de todos modos.
    marca_inicio = re.search(r"CRONOGRAMA\s+DE\s+OBLIGACIONES", texto_completo, re.IGNORECASE)
    marca_fin = re.search(r"BASE\s+LEGAL", texto_completo, re.IGNORECASE)
    inicio = marca_inicio.start() if marca_inicio else 0
    fin = marca_fin.start() if marca_fin else len(texto_completo)
    texto_relevante = texto_completo[inicio:fin]

    filas_resultado: list[dict] = []
    periodo_actual: str | None = None
    anio_periodo_actual: int | None = None
    fechas_del_periodo_actual = 0

    for m in _RE_TOKEN.finditer(texto_relevante):
        if m.group("periodo"):
            if periodo_actual is not None and fechas_del_periodo_actual < len(GRUPOS_COLUMNAS):
                logger.warning(
                    f"Cronograma {anio_esperado}: el periodo {periodo_actual} solo trajo "
                    f"{fechas_del_periodo_actual}/{len(GRUPOS_COLUMNAS)} fechas antes del siguiente periodo."
                )
            periodo_info = _parsear_periodo(m.group("periodo"))
            if not periodo_info:
                continue
            periodo_actual, anio_periodo_actual = periodo_info
            fechas_del_periodo_actual = 0
        elif m.group("fecha"):
            if periodo_actual is None or fechas_del_periodo_actual >= len(GRUPOS_COLUMNAS):
                continue  # fecha suelta antes del primer periodo, o sobrante -- se ignora
            fecha = _parsear_fecha_celda(m.group("fecha"), anio_periodo_actual)
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
            f"El cronograma {anio_esperado} se parseo con muy pocas filas ({len(filas_resultado)}) -- "
            "revisar si SUNAT cambio el formato de esta pagina."
        )

    return filas_resultado


def sincronizar_cronograma(db: Session, anio: int) -> dict:
    """Descarga, parsea y guarda (upsert) el cronograma de un ejercicio."""
    html = descargar_html_cronograma(anio)
    filas = parsear_cronograma_html(html, anio)

    guardadas = 0
    for fila in filas:
        existente = (
            db.query(CronogramaVencimiento)
            .filter(
                CronogramaVencimiento.periodo_tributario == fila["periodo_tributario"],
                CronogramaVencimiento.grupo == fila["grupo"],
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
                fecha_vencimiento=fecha_dt,
            ))
        guardadas += 1
    db.commit()

    periodos = sorted({f["periodo_tributario"] for f in filas})
    logger.info(
        f"Cronograma {anio} sincronizado: {guardadas} fila(s), "
        f"periodos {periodos[0] if periodos else '?'}..{periodos[-1] if periodos else '?'}"
    )
    return {"anio": anio, "periodos_procesados": len(periodos), "filas_guardadas": guardadas}


def grupo_para_empresa(ruc: str, es_buen_contribuyente: bool) -> str:
    """Determina que columna del cronograma le toca a una empresa."""
    if es_buen_contribuyente:
        return "buenos_contribuyentes"
    if not ruc or not ruc[-1].isdigit():
        return "0"  # RUC invalido/vacio -- no deberia pasar, pero no revienta
    ultimo_digito = int(ruc[-1])
    if ultimo_digito == 0:
        return "0"
    if ultimo_digito == 1:
        return "1"
    if ultimo_digito in (2, 3):
        return "2_3"
    if ultimo_digito in (4, 5):
        return "4_5"
    if ultimo_digito in (6, 7):
        return "6_7"
    return "8_9"  # 8 o 9


def asegurar_cronograma_vigente(db: Session) -> dict:
    """
    Idempotente: sincroniza el cronograma del anio actual si todavia no
    esta cargado (menos de 12 periodos guardados), y ademas el del anio
    siguiente si ya estamos en diciembre (SUNAT suele publicar el cronograma
    del ano siguiente en las ultimas semanas de diciembre). Pensada para
    llamarse sola -- al arrancar el backend y una vez al dia desde el
    scheduler -- sin necesitar que un humano dispare nada a mano. Si la
    descarga falla (SUNAT caida, cambio de formato, etc.) solo deja un
    warning en el log -- nunca debe tumbar el arranque del backend por esto.
    """
    hoy = datetime.now(timezone.utc)
    anios_a_revisar = [hoy.year]
    if hoy.month == 12:
        anios_a_revisar.append(hoy.year + 1)

    resultados = []
    for anio in anios_a_revisar:
        periodos_existentes = (
            db.query(CronogramaVencimiento.periodo_tributario)
            .filter(CronogramaVencimiento.periodo_tributario.like(f"{anio}-%"))
            .distinct()
            .count()
        )
        if periodos_existentes >= 12:
            continue
        try:
            resultado = sincronizar_cronograma(db, anio)
            resultados.append(resultado)
        except Exception as e:
            logger.warning(f"No se pudo sincronizar el cronograma {anio} automaticamente: {e}")

    return {"anios_sincronizados": resultados}


def _con_utc(momento: datetime) -> datetime:
    # SQLite (pruebas) devuelve datetimes "naive" aunque la columna sea
    # DateTime(timezone=True); Postgres (produccion) los devuelve con
    # tzinfo. Sin normalizar esto, comparar un naive con uno aware revienta
    # con TypeError -- mismo patron ya usado en routers/dashboard.py y
    # routers/admin.py.
    if momento is not None and momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


# "Baja de oficio", "Baja provisional", "Baja definitiva", "Suspension
# temporal" -- cualquiera de estos estados significa que el RUC no tiene
# obligaciones tributarias corrientes, asi que no tiene sentido seguir
# avisando vencimientos de esa empresa (confirmado explicitamente: baja y
# suspension se tratan igual). OJO: esto es DISTINTO de condicion_domicilio
# (Habido/No Habido/No Hallado) -- una empresa "No Habido" sigue activa
# como contribuyente y SI debe seguir apareciendo en el cronograma (de
# hecho es la que mas conviene vigilar).
_PATRONES_SIN_OBLIGACIONES = ("%BAJA%", "%SUSPENSION%")


def _empresas_para_cronograma(db: Session, tenant_id: str, usuario=None) -> list[Empresa]:
    """
    Empresas del tenant que corresponde considerar para el cronograma:
    activas (Empresa.activo=True) y sin un estado_contribuyente de baja o
    suspension. No filtra por condicion_domicilio a proposito -- "No
    Habido"/"No Hallado" siguen siendo contribuyentes activos y deben
    seguir apareciendo.

    `usuario` opcional (a pedido, control de acceso por rol): si se pasa y
    no es admin, se acota ademas a lo que tiene asignado -- igual criterio
    que filtrar_empresas_visibles en app/acceso.py, repetido aca en vez de
    importarlo porque este modulo no depende de FastAPI/HTTPException para
    nada mas. Se deja None para app/tareas.py (generar_tareas_mes), que
    sigue operando sobre TODO el tenant sin importar quien lo dispare --
    es generacion de datos idempotente, no una vista.
    """
    condiciones_excluidas = or_(*[
        Empresa.estado_contribuyente.ilike(patron) for patron in _PATRONES_SIN_OBLIGACIONES
    ])
    query = db.query(Empresa).filter(
        Empresa.tenant_id == tenant_id,
        Empresa.activo.is_(True),
        # OJO con NULL: si estado_contribuyente todavia no se leyo (None
        # hasta la primera consulta exitosa), NO hay que excluir a la
        # empresa -- "NOT (NULL ILIKE ...)" da NULL en SQL (ni
        # verdadero ni falso), asi que sin este or_() las empresas
        # recien creadas desaparecerian del cronograma por error.
        or_(
            Empresa.estado_contribuyente.is_(None),
            ~condiciones_excluidas,
        ),
    )
    if usuario is not None and usuario.rol != "admin":
        query = query.filter(Empresa.asignado_a_usuario_id == usuario.id)
    return query.all()


# Alias publico -- el modulo de Tareas/Agenda (app/tareas.py) reusa este
# mismo filtro (activas, sin baja de oficio) para decidir a que empresas
# les corresponde generar tareas, asi que se expone sin el guion bajo en
# vez de duplicar la consulta en otro archivo.
empresas_para_cronograma = _empresas_para_cronograma


def proximos_vencimientos_por_tenant(db: Session, tenant_id: str, dias_adelante: int = 15, usuario=None) -> list[dict]:
    """
    Para cada empresa activa del tenant (sin baja de oficio), busca su
    PROXIMO vencimiento (el primero con fecha >= hoy) segun el grupo que le
    corresponde -- pensado para el aviso del Dashboard. Solo devuelve los
    que caen dentro de `dias_adelante` dias, para no saturar el aviso con
    vencimientos lejanos. `usuario` opcional -- ver _empresas_para_cronograma.
    """
    empresas = _empresas_para_cronograma(db, tenant_id, usuario)
    if not empresas:
        return []

    hoy = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    limite = hoy + timedelta(days=dias_adelante)

    resultado = []
    for empresa in empresas:
        grupo = grupo_para_empresa(empresa.ruc, empresa.es_buen_contribuyente)
        proximo = (
            db.query(CronogramaVencimiento)
            .filter(
                CronogramaVencimiento.grupo == grupo,
                CronogramaVencimiento.fecha_vencimiento >= hoy,
            )
            .order_by(CronogramaVencimiento.fecha_vencimiento.asc())
            .first()
        )
        if proximo is None:
            continue
        fecha_vencimiento = _con_utc(proximo.fecha_vencimiento)
        if fecha_vencimiento <= limite:
            dias_restantes = (fecha_vencimiento.date() - hoy.date()).days
            resultado.append({
                "empresa_id": empresa.id,
                "empresa_ruc": empresa.ruc,
                "empresa_razon_social": empresa.razon_social,
                "periodo_tributario": proximo.periodo_tributario,
                "grupo": grupo,
                "fecha_vencimiento": fecha_vencimiento,
                "dias_restantes": dias_restantes,
            })

    resultado.sort(key=lambda r: r["fecha_vencimiento"])
    return resultado


def agenda_mes_por_tenant(db: Session, tenant_id: str, anio: int, mes: int, usuario=None) -> list[dict]:
    """
    Todas las empresas activas del tenant (sin baja de oficio) cuyo
    vencimiento (segun su grupo) cae en el mes/anio pedido -- para la
    vista de calendario del modulo Cronograma. `usuario` opcional -- ver
    _empresas_para_cronograma.
    """
    inicio = datetime(anio, mes, 1, tzinfo=timezone.utc)
    if mes == 12:
        fin = datetime(anio + 1, 1, 1, tzinfo=timezone.utc)
    else:
        fin = datetime(anio, mes + 1, 1, tzinfo=timezone.utc)

    empresas = _empresas_para_cronograma(db, tenant_id, usuario)
    if not empresas:
        return []

    grupos_usados = {grupo_para_empresa(e.ruc, e.es_buen_contribuyente) for e in empresas}
    vencimientos_del_mes = (
        db.query(CronogramaVencimiento)
        .filter(
            CronogramaVencimiento.grupo.in_(grupos_usados),
            CronogramaVencimiento.fecha_vencimiento >= inicio,
            CronogramaVencimiento.fecha_vencimiento < fin,
        )
        .all()
    )
    por_grupo: dict[str, list[CronogramaVencimiento]] = {}
    for v in vencimientos_del_mes:
        por_grupo.setdefault(v.grupo, []).append(v)

    resultado = []
    for empresa in empresas:
        grupo = grupo_para_empresa(empresa.ruc, empresa.es_buen_contribuyente)
        for v in por_grupo.get(grupo, []):
            resultado.append({
                "empresa_id": empresa.id,
                "empresa_ruc": empresa.ruc,
                "empresa_razon_social": empresa.razon_social,
                "periodo_tributario": v.periodo_tributario,
                "grupo": grupo,
                "fecha_vencimiento": _con_utc(v.fecha_vencimiento),
            })

    resultado.sort(key=lambda r: r["fecha_vencimiento"])
    return resultado
