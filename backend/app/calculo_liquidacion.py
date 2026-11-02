"""
Calculo del IGV y la Renta de un periodo para la Liquidacion en vivo (Bloque 2
del piloto, PLAN_LIQUIDACION_EN_VIVO.md). Estima las casillas del 0621, con su
mismo numero, a partir de lo que leyeron los lectores del Bloque 1:
  - ventas y compras: propuesta del SIRE del periodo
  - percepciones (171): comprobantes recibidos del mes y liquidaciones de
    Aduanas ya pagadas (parametros 3.6 y 3.7); retenciones (179):
    comprobantes recibidos del mes, sin los revertidos (3.5)
  - arrastres del mes anterior (145, 168, 176): su 0621 o, si no se declaro,
    su estimado (4.2)
  - pagos previos: boletas 1662 del periodo (3.8)
El orden sale de los 0621 reales de las empresas piloto (4.1): 131 - 178 =
140; 140 - 145 = 184; si 184 es positivo se aplican primero las percepciones
(171 + 168) y despues las retenciones (179 + 176); lo que no alcanza a
aplicarse pasa al mes siguiente (164 y 165) y lo que queda es el 681. Como el
formulario, cada casilla de datos se redondea a soles enteros y las de
resultado se calculan con las ya redondeadas (4.3).
"""
from datetime import date, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.cronograma_sunat import grupo_para_empresa
from app.hora_peru import ZONA_PERU, hoy_peru
from app.jobs_liquidacion import sumar_meses
from app.models import (
    CronogramaVencimiento, DeclaracionSunat, Empresa, LiquidacionCalculo, LiquidacionComprobante,
    LiquidacionDeclaracion, LiquidacionEmpresa, LiquidacionLectura, LiquidacionRetencionPercepcion,
)

# Pago a cuenta de Renta (parametro 6.1): General y MYPE sobre el tope pagan
# el mayor entre el coeficiente y 1.5 %; MYPE hasta el tope 1 %; RER 1.5 %.
PORCENTAJE_MINIMO = 0.015
PORCENTAJE_MYPE = 0.01
PORCENTAJE_RER = 0.015
TOPE_MYPE_UIT = 300
# UIT por ano (6.2). La de 2026 falta que la confirme el contador (plan, seccion 7).
UIT = {2025: 5350, 2026: 5500}
# Codigos de tributo de las boletas 1662 (3.8), por confirmar con el contador.
TRIBUTO_IGV = "1011"
TRIBUTOS_RENTA = ("3031", "3121", "3111")
# Comprobantes de importacion en el Registro de Compras: DAM, despacho
# simplificado, courier y liquidacion de cobranza (crédito de la casilla 115).
TIPOS_IMPORTACION = ("50", "52", "53", "54")
# Si falta el 0621 del mes anterior se encadenan estimados, hasta estos meses atras.
MESES_ENCADENADOS = 3
# Si en el ultimo 0621 la base de la Renta (301) fue menos de la mitad o mas
# del doble de las ventas declaradas (p. ej. quien vende por cuenta de otros y
# declara solo su comision), el estimado usa esa misma proporcion.
PROPORCION_RENTA_NORMAL = (0.5, 2.0)
# Conciliacion con el 0621 presentado (7.1): una casilla difiere si se aleja mas que esto.
UMBRAL_DIFERENCIA = 10
# "Requiere atencion" (4.6): el IGV sube esto o mas frente al mes anterior o al mismo mes del ano anterior.
ALZA_DE_ATENCION = 0.15

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "setiembre", "octubre",
         "noviembre", "diciembre")


def texto_periodo(periodo: str) -> str:
    return f"{MESES[int(periodo[5:7]) - 1]} {periodo[:4]}"


def soles(monto: float | None) -> int:
    """A soles enteros como el formulario: la mitad sube."""
    return int(Decimal(str(monto or 0)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# --- 0621 ya presentados ---

def _seccion(casilla: str) -> str | None:
    if not casilla.isdigit():
        return None
    n = int(casilla)
    if 100 <= n < 200 or n == 681:
        return "igv"
    if 300 <= n < 340 or n == 380 or n == 682:
        return "renta"
    return None


def casillas_declaradas(declaraciones: list) -> dict[str, float]:
    """
    Casillas de un periodo segun sus 0621, por fecha de presentacion: cada
    seccion (IGV o Renta) sale de la ultima declaracion que la trae. Manda la
    fecha y no la marca de rectificatoria: BASCAT 02/2026 tiene dos
    "originales" y la segunda trae solo el IGV, asi que la Renta sigue siendo
    la de la primera.
    """
    resultado: dict[str, float] = {}
    orden = sorted(
        declaraciones,
        key=lambda d: (d.fecha_presentacion or date.min, int(d.num_orden) if d.num_orden.isdigit() else 0),
    )
    for d in orden:
        numericas = {k: float(v) for k, v in d.casillas.items() if isinstance(v, (int, float)) and _seccion(k)}
        for seccion in {_seccion(k) for k in numericas}:
            resultado = {k: v for k, v in resultado.items() if _seccion(k) != seccion}
        resultado.update(numericas)
    return resultado


def arrastre_de(casillas: dict) -> dict[str, int]:
    """Lo que un mes deja al siguiente: saldo a favor (145), percepciones (168) y retenciones (176) no aplicadas."""
    return {
        "145": max(0, -soles(casillas.get("184"))),
        "168": soles(casillas.get("164")),
        "176": soles(casillas.get("165")),
    }


# --- Calculo ---

def sumar_sire(ventas: list, compras: list) -> dict[str, float]:
    """
    Casillas de ventas y compras con centimos, desde la propuesta del SIRE,
    como las arma SUNAT (BASCAT 09/2026 cuadra al sol): las columnas "BI
    Gravada" e "IGV" de todos los comprobantes, notas de credito incluidas
    (vienen en negativo), van a 100 y 101, y las de "Dscto" a 102 y 103. Los
    montos ya vienen en soles aunque el comprobante sea en dolares. La base
    de la Renta (301) es la venta neta: gravada, no gravada y exportacion,
    menos las notas de credito (6.3). En compras las notas de credito restan
    del credito.
    """
    s = dict.fromkeys(("100", "101", "102", "103", "105", "106", "109", "301", "107", "108", "110", "111", "114", "115"), 0.0)
    for c in ventas:
        exonerado, inafecto = _num(c.datos.get("mto exonerado")), _num(c.datos.get("mto inafecto"))
        s["100"] += c.base_gravada
        s["101"] += c.igv
        s["102"] -= c.descuento_base
        s["103"] -= c.descuento_igv
        s["105"] += exonerado
        s["109"] += inafecto
        s["106"] += c.exportacion
        s["301"] += c.base_gravada + c.descuento_base + c.exportacion + exonerado + inafecto
    for c in compras:
        if c.tipo_comprobante in TIPOS_IMPORTACION:
            s["114"] += c.base_gravada
            s["115"] += c.igv
        else:
            s["107"] += c.base_gravada
            s["108"] += c.igv
        s["110"] += c.base_dgng
        s["111"] += c.igv_dgng
    return s


def determinar_igv(c: dict[str, int]) -> dict[str, int]:
    """
    Casillas de resultado del IGV desde las de datos, ya en soles enteros:
    131, 178, 145, 171, 168, 179, 176 y 185 (pagos previos).
    """
    r = dict(c)
    r["140"] = c["131"] - c["178"]
    r["184"] = r["140"] - c["145"]
    percepciones = c["171"] + c["168"]
    retenciones = c["179"] + c["176"]
    deuda = max(r["184"], 0)
    aplicadas = min(deuda, percepciones)
    deuda -= aplicadas
    r["164"] = percepciones - aplicadas
    aplicadas = min(deuda, retenciones)
    deuda -= aplicadas
    r["165"] = retenciones - aplicadas
    r["681"] = deuda
    return r


def porcentaje_renta(
    regimen: str | None, coeficiente: float | None, acumulado: float, uit: int | None, supero_tope: bool,
    porcentaje_ultimo_0621: float | None,
) -> tuple[float | None, str]:
    """
    Porcentaje del pago a cuenta y la regla que se uso (6.1). acumulado: los
    ingresos netos del ano hasta este mes inclusive (para el tope de la MYPE).
    """
    def mayor() -> tuple[float, str]:
        if coeficiente and coeficiente > PORCENTAJE_MINIMO:
            return coeficiente, f"el coeficiente {coeficiente:.4f} del último 0621, mayor que 1.5 %"
        if coeficiente:
            return PORCENTAJE_MINIMO, f"1.5 %, mayor que el coeficiente {coeficiente:.4f} del último 0621"
        return PORCENTAJE_MINIMO, "1.5 % (no hay coeficiente en los 0621 leídos)"

    if regimen == "especial":
        return PORCENTAJE_RER, "RER: 1.5 % de los ingresos netos"
    if regimen == "general":
        p, regla = mayor()
        return p, f"Régimen General: {regla}"
    if regimen == "mype":
        tope = TOPE_MYPE_UIT * uit if uit else None
        if supero_tope:
            p, regla = mayor()
            return p, f"MYPE que ya pasó el tope de 300 UIT este año: {regla}"
        if tope is not None and acumulado > tope:
            p, regla = mayor()
            return p, f"MYPE: con este mes los ingresos del año (S/ {acumulado:,.0f}) pasan el tope de 300 UIT (S/ {tope:,}): {regla}"
        if tope is None:
            return PORCENTAJE_MYPE, "MYPE: 1 % (falta la UIT del año para revisar el tope)"
        return PORCENTAJE_MYPE, f"MYPE: 1 %; ingresos del año S/ {acumulado:,.0f}, debajo del tope de 300 UIT (S/ {tope:,})"
    if porcentaje_ultimo_0621:
        return porcentaje_ultimo_0621, f"{porcentaje_ultimo_0621 * 100:.2f} %, el que se usó en el último 0621"
    return None, "Falta el régimen tributario: confírmalo en la configuración."


class _Datos:
    """Lo guardado de una empresa que usa el calculo, leido una sola vez (cada consulta queda en memoria)."""

    def __init__(self, db: Session, empresa_id: str):
        self.db = db
        self.empresa_id = empresa_id
        por_periodo: dict[str, list] = {}
        for d in db.query(LiquidacionDeclaracion).filter(LiquidacionDeclaracion.empresa_id == empresa_id):
            por_periodo.setdefault(d.periodo, []).append(d)
        self.declaraciones = por_periodo
        self._declaradas: dict[str, dict] = {}
        self._consultas: dict[tuple, object] = {}

    def _una_vez(self, clave: tuple, consulta):
        if clave not in self._consultas:
            self._consultas[clave] = consulta()
        return self._consultas[clave]

    def declarado(self, periodo: str) -> dict[str, float]:
        if periodo not in self._declaradas:
            self._declaradas[periodo] = casillas_declaradas(self.declaraciones.get(periodo, []))
        return self._declaradas[periodo]

    def ultima_lectura(self, fuente: str, periodo: str) -> LiquidacionLectura | None:
        return self._una_vez(("lectura", fuente, periodo), lambda: (
            self.db.query(LiquidacionLectura)
            .filter(
                LiquidacionLectura.empresa_id == self.empresa_id,
                LiquidacionLectura.fuente == fuente,
                LiquidacionLectura.estado == "completado",
                LiquidacionLectura.periodo_desde <= periodo,
                LiquidacionLectura.periodo_hasta >= periodo,
            )
            .order_by(LiquidacionLectura.finalizado_en.desc())
            .first()
        ))

    def comprobantes(self, libro: str, periodo: str) -> list[LiquidacionComprobante]:
        return self._una_vez(("comprobantes", libro, periodo), lambda: self.db.query(LiquidacionComprobante).filter(
            LiquidacionComprobante.empresa_id == self.empresa_id,
            LiquidacionComprobante.libro == libro,
            LiquidacionComprobante.fuente == "propuesta",
            LiquidacionComprobante.periodo == periodo,
        ).all())

    def retenciones_percepciones(self, periodo: str) -> list[LiquidacionRetencionPercepcion]:
        return self._una_vez(("retper", periodo), lambda: self.db.query(LiquidacionRetencionPercepcion).filter(
            LiquidacionRetencionPercepcion.empresa_id == self.empresa_id,
            LiquidacionRetencionPercepcion.periodo == periodo,
        ).all())

    def pagos(self, periodo: str, tributos: tuple[str, ...]) -> float:
        return self._una_vez(("pagos", periodo, tributos), lambda: sum(
            p.importe_pagado
            for p in self.db.query(DeclaracionSunat).filter(
                DeclaracionSunat.empresa_id == self.empresa_id,
                DeclaracionSunat.periodo == periodo,
                DeclaracionSunat.formulario == "1662",
                DeclaracionSunat.cod_tributo.in_(tributos),
            )
        ))


class _DatosAl(_Datos):
    """
    Los mismos datos, pero del periodo solo lo emitido hasta `corte`: con eso
    se rehace cada dia del mes para el grafico "Como va el mes, dia a dia".
    Comparte las consultas ya hechas con `base`.
    """

    def __init__(self, base: _Datos, periodo: str, corte: date):
        self.__dict__.update(base.__dict__)
        self._periodo, self._corte = periodo, corte

    def _hasta_el_corte(self, filas: list, periodo: str) -> list:
        if periodo != self._periodo:
            return filas
        return [f for f in filas if f.fecha_emision is None or f.fecha_emision <= self._corte]

    def comprobantes(self, libro: str, periodo: str) -> list[LiquidacionComprobante]:
        return self._hasta_el_corte(super().comprobantes(libro, periodo), periodo)

    def retenciones_percepciones(self, periodo: str) -> list[LiquidacionRetencionPercepcion]:
        return self._hasta_el_corte(super().retenciones_percepciones(periodo), periodo)


def _linea(casilla: str | None, concepto: str, monto: int | None, tipo: str = "dato", fuente: str | None = None,
           declarado: dict | None = None, signo: int = 1) -> dict:
    d = (declarado or {}).get(casilla) if casilla else None
    return {
        "casilla": casilla, "concepto": concepto, "monto": monto, "tipo": tipo, "fuente": fuente,
        "declarado": soles(d) if d is not None else None, "signo": signo,
    }


def _calcular(datos: _Datos, periodo: str, regimen: str | None, nivel: int = 0) -> dict:
    avisos: list[str] = []
    fechas: dict[str, object] = {}
    lecturas = {f: datos.ultima_lectura(f, periodo) for f in ("sire", "retenciones", "percepciones", "aduanas", "declaraciones")}
    for fuente, lectura in lecturas.items():
        fechas[fuente] = lectura.finalizado_en if lectura else None

    # Ventas y compras
    ventas, compras = datos.comprobantes("RVIE", periodo), datos.comprobantes("RCE", periodo)
    sire = sumar_sire(ventas, compras)
    c = {k: soles(v) for k, v in sire.items()}
    c["131"] = c["101"] - c["103"]
    if lecturas["sire"] is None:
        avisos.append(f"Faltan las ventas y compras del SIRE de {texto_periodo(periodo)}: usa \"Leer datos de SUNAT\".")

    # Lo que se toma de los 0621 anteriores: coeficiente (380), porcentaje
    # aplicado (315), coeficiente de prorrata del credito (173) y cuanto de
    # las ventas fue base de la Renta.
    coeficiente = porcentaje_ultimo = prorrata = base_renta = None
    for p in sorted((p for p in datos.declaraciones if p < periodo), reverse=True):
        dec = datos.declarado(p)
        if coeficiente is None and _num(dec.get("380")) > 0:
            coeficiente = _num(dec.get("380"))
        if porcentaje_ultimo is None and (_num(dec.get("315")) or _num(dec.get("380"))):
            porcentaje_ultimo = max(_num(dec.get("380")), _num(dec.get("315")) / 100)
        if prorrata is None and "173" in dec:
            prorrata = _num(dec.get("173"))
        ventas_declaradas = sum(_num(dec.get(k)) for k in ("100", "105", "106", "109", "112")) - _num(dec.get("102"))
        if base_renta is None and ventas_declaradas > 0 and _num(dec.get("301")) > 0:
            base_renta = (p, _num(dec.get("301")), ventas_declaradas)

    # Credito fiscal. La propuesta del SIRE pone todas las compras como
    # destinadas a ventas gravadas; una empresa que solo vende exonerado o
    # inafecto las declara sin credito (casilla 113, MISKY SONKO 09/2026) y una
    # con ventas de los dos tipos aplica su prorrata (173).
    igv_compras = sire["108"] + sire["111"] + sire["115"]
    credito_nota = None
    if c["100"] <= 0 and not c["106"] and c["105"] + c["109"] > 0 and igv_compras > 0:
        c["178"] = 0
        credito_regla = f"SIRE: {len(compras)} compras; sin crédito porque este mes solo hay ventas no gravadas"
        credito_nota = f"Sin crédito: este mes solo hay ventas no gravadas (IGV de compras S/ {soles(igv_compras):,})"
        avisos.append(
            f"Este mes solo hay ventas no gravadas: el IGV de las compras (S/ {soles(igv_compras):,}) no da crédito fiscal (casilla 113)."
        )
    elif prorrata is not None and 0 < prorrata < 1 and igv_compras > 0:
        c["178"] = soles(igv_compras * prorrata)
        credito_regla = f"SIRE: {len(compras)} compras; prorrata {prorrata:.4f} del último 0621"
        credito_nota = f"Con la prorrata {prorrata:.4f} del último 0621, sobre S/ {soles(igv_compras):,} de IGV de compras"
        avisos.append(
            f"Se aplica la prorrata del último 0621 ({prorrata:.4f}): crédito de S/ {c['178']:,} sobre S/ {soles(igv_compras):,} de IGV de compras."
        )
    else:
        c["178"] = c["108"] + c["111"] + c["115"]
        credito_regla = f"SIRE: {len(compras)} compras"

    # Percepciones y retenciones del mes
    retper = datos.retenciones_percepciones(periodo)
    percep_comprobantes = sum(r.monto for r in retper if r.tipo == "percepcion" and r.origen == "comprobante" and r.cuenta)
    percep_aduanas = sum(r.monto for r in retper if r.tipo == "percepcion" and r.origen == "aduanas" and r.cuenta)
    pendientes_aduanas = sum(r.monto for r in retper if r.tipo == "percepcion" and r.origen == "aduanas" and not r.cuenta)
    retenciones = sum(r.monto for r in retper if r.tipo == "retencion" and r.cuenta)
    c["171"] = soles(percep_comprobantes + percep_aduanas)
    c["179"] = soles(retenciones)
    if pendientes_aduanas:
        avisos.append(
            f"Percepciones de importación por S/ {soles(pendientes_aduanas):,} todavía sin pagar: no se restan hasta que se paguen."
        )
    for fuente, texto in (("retenciones", "las retenciones"), ("percepciones", "las percepciones"), ("aduanas", "las percepciones de importación")):
        if lecturas[fuente] is None:
            avisos.append(f"Faltan {texto} de {texto_periodo(periodo)}: se toman como 0.")

    # Arrastre del mes anterior
    anterior = sumar_meses(periodo, -1)
    declarado_anterior = datos.declarado(anterior)
    origen_arrastre = None
    if any(k in declarado_anterior for k in ("140", "184", "131", "178")):
        c.update(arrastre_de(declarado_anterior))
        ultima = max(datos.declaraciones[anterior], key=lambda d: d.fecha_presentacion or date.min)
        origen_arrastre = f"0621 de {texto_periodo(anterior)} (orden {ultima.num_orden})"
    elif nivel < MESES_ENCADENADOS and datos.ultima_lectura("sire", anterior) is not None:
        previo = _calcular(datos, anterior, regimen, nivel + 1)
        c.update(arrastre_de(previo["casillas"]))
        origen_arrastre = f"estimado de {texto_periodo(anterior)} (aún sin 0621)"
    else:
        c.update({"145": 0, "168": 0, "176": 0})
        avisos.append(
            f"No hay 0621 de {texto_periodo(anterior)} ni datos para estimarlo: el saldo a favor y lo no aplicado del mes anterior se toman como 0."
        )

    c["185"] = soles(datos.pagos(periodo, (TRIBUTO_IGV,)))
    c = determinar_igv(c)

    # Renta
    base_regla = "Ventas netas: gravadas, no gravadas y exportación, menos notas de crédito"
    if base_renta:
        p, ingresos, ventas_declaradas = base_renta
        proporcion = ingresos / ventas_declaradas
        if not PROPORCION_RENTA_NORMAL[0] <= proporcion <= PROPORCION_RENTA_NORMAL[1]:
            c["301"] = soles(sire["301"] * proporcion)
            base_regla = f"{proporcion * 100:.1f} % de las ventas netas, la proporción del 0621 de {texto_periodo(p)}"
            avisos.append(
                f"En el 0621 de {texto_periodo(p)} los ingresos de la Renta (S/ {soles(ingresos):,}) fueron el "
                f"{proporcion * 100:.1f} % de las ventas declaradas (S/ {soles(ventas_declaradas):,}): se usa la misma proporción."
            )
    anio = int(periodo[:4])
    meses_previos = [f"{anio}-{m:02d}" for m in range(1, int(periodo[5:7]))]
    acumulado = float(c["301"])
    supero_tope = False
    for p in meses_previos:
        dec = datos.declarado(p)
        acumulado += soles(dec.get("301"))
        if _num(dec.get("315")) > PORCENTAJE_MYPE * 100:
            supero_tope = True
    porcentaje, regla = porcentaje_renta(regimen, coeficiente, acumulado, UIT.get(anio), supero_tope, porcentaje_ultimo)
    c["312"] = soles(c["301"] * porcentaje) if porcentaje is not None else 0
    c["317"] = soles(datos.pagos(periodo, TRIBUTOS_RENTA))
    if porcentaje is None:
        avisos.append(regla)

    return {
        "periodo": periodo,
        "casillas": c,
        "igv_por_pagar": max(c["681"] - c["185"], 0),
        "saldo_a_favor": max(-c["184"], 0),
        "renta_porcentaje": porcentaje,
        "renta_regla": regla,
        "renta_por_pagar": max(c["312"] - c["317"], 0) if porcentaje is not None else None,
        "ventas": len(ventas),
        "compras": len(compras),
        "credito_regla": credito_regla,
        "credito_nota": credito_nota,
        "base_regla": base_regla,
        "percepciones_comprobantes": soles(percep_comprobantes),
        "percepciones_aduanas": soles(percep_aduanas),
        "origen_arrastre": origen_arrastre,
        "fechas": fechas,
        "avisos": avisos,
    }


def _lineas_monto(c: dict, r: dict) -> list[dict]:
    """
    "Como se llega al monto" en lenguaje simple, como el boceto. Cada resta es
    lo que de verdad se aplica, asi que las lineas suman el resultado; lo que
    no alcanza a aplicarse se anota porque pasa al mes siguiente.
    """
    def linea(concepto, monto, signo=-1, fuente=None, nota=None, tipo="dato"):
        return {"concepto": concepto, "monto": monto, "signo": signo, "fuente": fuente, "nota": nota, "tipo": tipo}

    percepciones, retenciones = c["171"] + c["168"], c["179"] + c["176"]
    fuente_compras = f"SIRE compras · {r['compras']} comprobantes"
    if c["115"]:
        fuente_compras += f" · incluye importaciones (IGV S/ {c['115']:,})"
    fuente_percepciones = f"Comprobantes S/ {r['percepciones_comprobantes']:,} · Aduanas S/ {r['percepciones_aduanas']:,}"
    if c["168"]:
        fuente_percepciones += f" · de meses anteriores S/ {c['168']:,}"
    fuente_retenciones = f"Comprobantes de retención recibidos S/ {c['179']:,}"
    if c["176"]:
        fuente_retenciones += f" · de meses anteriores S/ {c['176']:,}"

    def no_aplicadas(monto):
        return f"S/ {monto:,} no alcanzan a aplicarse: pasan al mes siguiente" if monto else None

    lineas = [
        linea("IGV de ventas gravadas", c["131"], 1, f"SIRE ventas · {r['ventas']} comprobantes · base S/ {c['100'] - c['102']:,}"),
        linea("Crédito fiscal de compras", c["178"], fuente=fuente_compras, nota=r["credito_nota"]),
        linea("Saldo a favor del mes anterior", c["145"],
              fuente=r["origen_arrastre"] or "Sin 0621 ni estimado del mes anterior: se toma 0"),
        linea("Percepciones del mes y no aplicadas", percepciones - c["164"], fuente=fuente_percepciones, nota=no_aplicadas(c["164"])),
        linea("Retenciones del mes y no aplicadas", retenciones - c["165"], fuente=fuente_retenciones, nota=no_aplicadas(c["165"])),
    ]
    if c["184"] < 0:
        lineas.append(linea("Saldo a favor", -c["184"], 1, nota="Pasa al mes siguiente", tipo="total"))
    elif c["185"]:
        lineas += [
            linea("IGV a pagar", c["681"], 1, tipo="subtotal"),
            linea("Pagos ya hechos del periodo", c["185"], fuente="Boletas 1662 (tributo 1011)"),
            linea("IGV a pagar hoy", max(c["681"] - c["185"], 0), 1, tipo="total"),
        ]
    else:
        lineas.append(linea("IGV a pagar hoy", c["681"], 1, tipo="total"))
    return lineas


def _igv_declarado(datos: _Datos, periodo: str) -> int | None:
    """IGV a pagar (681) del 0621 de un periodo; None si no se declaro el IGV."""
    dec = datos.declarado(periodo)
    return soles(dec.get("681")) if any(k in dec for k in ("681", "184", "140", "131")) else None


def _comparacion(datos: _Datos, periodo: str) -> list[dict]:
    """Como en el boceto: el IGV a pagar del mismo mes del ano anterior, del mes anterior y el promedio de 12 meses."""
    mismo, anterior = sumar_meses(periodo, -12), sumar_meses(periodo, -1)
    ultimos = [v for v in (_igv_declarado(datos, sumar_meses(periodo, -n)) for n in range(1, 13)) if v is not None]
    return [
        {"concepto": f"{texto_periodo(mismo).capitalize()} (mismo mes)", "periodo": mismo, "igv": _igv_declarado(datos, mismo)},
        {"concepto": f"{texto_periodo(anterior).capitalize()} (mes anterior)", "periodo": anterior,
         "igv": _igv_declarado(datos, anterior)},
        {"concepto": f"Promedio de los últimos {len(ultimos)} meses declarados" if ultimos else "Promedio de los últimos 12 meses",
         "periodo": None, "igv": round(sum(ultimos) / len(ultimos)) if ultimos else None},
    ]


def _estado_mes(declarado: dict | None, lineas: list[dict], hay_datos: bool) -> tuple[str, int]:
    """
    Estado del mes (4.8): en_curso hasta que aparece el 0621; despues
    conciliado o con_diferencias segun las casillas (7.1), o solo declarado
    si no hay estimado con que comparar. Devuelve tambien cuantas difieren.
    """
    if not declarado:
        return "en_curso", 0
    if not hay_datos:
        return "declarado", 0
    diferencias = sum(
        1 for l in lineas
        if l["declarado"] is not None and l["monto"] is not None and abs(l["monto"] - l["declarado"]) > UMBRAL_DIFERENCIA
    )
    return ("con_diferencias" if diferencias else "conciliado"), diferencias


def _atencion(c: dict, comparacion: list[dict], declarado: dict | None, diferencias: int, lectura_sire, hoy: date) -> list[str]:
    """
    Motivos de "Requiere atencion" (4.6) que ya se pueden revisar: alza del
    IGV frente al mes anterior o al mismo mes del ano anterior, diferencias
    con el 0621 presentado y datos del SIRE de mas de un dia. (El credito en
    riesgo llega con la Fase 5; la API del SIRE la revisa el panel.)
    """
    motivos = []
    if not declarado:
        for item in comparacion[:2]:
            if item["igv"]:
                alza = (c["681"] - item["igv"]) / item["igv"]
                if alza >= ALZA_DE_ATENCION:
                    motivos.append(
                        f"IGV {round(alza * 100)} % más alto que {item['concepto'].split(' (')[0]} (S/ {item['igv']:,})"
                    )
        if lectura_sire is not None:
            leido = (lectura_sire if lectura_sire.tzinfo else lectura_sire.replace(tzinfo=timezone.utc)).astimezone(ZONA_PERU).date()
            if leido < hoy - timedelta(days=1):
                motivos.append(f"Los datos del SIRE son del {leido:%d/%m}: no se han vuelto a leer")
    if diferencias:
        motivos.append(f"{diferencias} casilla(s) difieren en más de S/ {UMBRAL_DIFERENCIA} del 0621 presentado")
    return motivos


def serie_diaria(db: Session, empresa: Empresa, periodo: str, hoy: date) -> list[dict]:
    """
    Cada dia del periodo, hasta hoy, rehecho con lo emitido hasta ese dia: IGV
    de ventas (131), credito fiscal (178) e IGV a pagar (681), para "Como va
    el mes, dia a dia". Usa la fecha de emision de la ultima propuesta del
    SIRE; las fotos diarias (3.12) muestran ademas lo que SUNAT tenia cada dia.
    """
    config = db.get(LiquidacionEmpresa, empresa.id)
    regimen = config.regimen if config else None
    datos = _Datos(db, empresa.id)
    if datos.ultima_lectura("sire", periodo) is None:
        return []
    inicio = date(int(periodo[:4]), int(periodo[5:7]), 1)
    fin = min((inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1), hoy)
    puntos = []
    dia = inicio
    while dia <= fin:
        c = _calcular(_DatosAl(datos, periodo, dia), periodo, regimen)["casillas"]
        puntos.append({"fecha": dia, "ventas": c["131"], "credito": c["178"], "por_pagar": c["681"]})
        dia += timedelta(days=1)
    return puntos


def vencimiento(db: Session, empresa: Empresa, periodo: str):
    fila = db.query(CronogramaVencimiento).filter(
        CronogramaVencimiento.periodo_tributario == periodo,
        CronogramaVencimiento.tipo == "mensual",
        CronogramaVencimiento.grupo == grupo_para_empresa(empresa.ruc, empresa.es_buen_contribuyente),
    ).first()
    if fila is None:
        return None
    # La fecha se guarda como las 00:00 UTC del dia (hora_peru.etiqueta_de_dia).
    f = fila.fecha_vencimiento
    return (f.astimezone(timezone.utc) if f.tzinfo else f).date()


def calcular_periodo(db: Session, empresa: Empresa, periodo: str, hoy: date | None = None) -> dict:
    """El estimado del periodo con sus lineas de "como se llega al monto", y lo declarado si ya hay 0621."""
    config = db.get(LiquidacionEmpresa, empresa.id)
    regimen = config.regimen if config else None
    datos = _Datos(db, empresa.id)
    r = _calcular(datos, periodo, regimen)
    c = r["casillas"]
    declarado = datos.declarado(periodo) or None
    ultima_declaracion = (
        max(datos.declaraciones[periodo], key=lambda d: d.fecha_presentacion or date.min) if declarado else None
    )
    sire = f"SIRE: {r['ventas']} ventas"
    percepciones = f"Comprobantes S/ {r['percepciones_comprobantes']:,} + Aduanas S/ {r['percepciones_aduanas']:,}"
    lineas_igv = [
        _linea("101", "IGV de ventas", c["101"], fuente=sire, declarado=declarado),
        _linea("103", "Notas de crédito y descuentos", c["103"], fuente=sire, declarado=declarado, signo=-1),
        _linea("131", "IGV de ventas neto", c["131"], "subtotal", declarado=declarado),
        _linea("178", "Crédito fiscal de compras", c["178"], fuente=r["credito_regla"], declarado=declarado, signo=-1),
        _linea("140", "Impuesto resultante", c["140"], "subtotal", declarado=declarado),
        _linea("145", "Saldo a favor del mes anterior", c["145"], fuente=r["origen_arrastre"], declarado=declarado, signo=-1),
        _linea("184", "Tributo del mes", c["184"], "subtotal", declarado=declarado),
        _linea("171", "Percepciones del mes", c["171"], fuente=percepciones, declarado=declarado, signo=-1),
        _linea("168", "Percepciones de meses anteriores", c["168"], fuente=r["origen_arrastre"], declarado=declarado, signo=-1),
        _linea("179", "Retenciones del mes", c["179"], fuente="Comprobantes de retención recibidos", declarado=declarado, signo=-1),
        _linea("176", "Retenciones de meses anteriores", c["176"], fuente=r["origen_arrastre"], declarado=declarado, signo=-1),
        _linea("681", "IGV a pagar", c["681"], "total", declarado=declarado),
        _linea("185", "Pagos ya hechos del periodo", c["185"], fuente="Boletas 1662 (tributo 1011)", declarado=declarado, signo=-1),
    ]
    siguiente = [
        _linea(None, "Saldo a favor que pasa al mes siguiente", r["saldo_a_favor"], "arrastre"),
        _linea("164", "Percepciones que pasan al mes siguiente", c["164"], "arrastre", declarado=declarado),
        _linea("165", "Retenciones que pasan al mes siguiente", c["165"], "arrastre", declarado=declarado),
    ]
    lineas_renta = [
        _linea("301", "Ingresos netos del mes", c["301"], fuente=f"{sire}. {r['base_regla']}", declarado=declarado),
        _linea("312", "Pago a cuenta", c["312"], "subtotal", fuente=r["renta_regla"], declarado=declarado),
        _linea("317", "Pagos ya hechos del periodo", c["317"], fuente="Boletas 1662 (tributos " + ", ".join(TRIBUTOS_RENTA) + ")", declarado=declarado, signo=-1),
    ]
    fechas = [f for f in r["fechas"].values() if f is not None]
    comparacion = _comparacion(datos, periodo)
    estado_mes, diferencias = _estado_mes(declarado, lineas_igv + siguiente + lineas_renta, r["fechas"].get("sire") is not None)
    return {
        "periodo": periodo,
        "regimen": regimen,
        "vence": vencimiento(db, empresa, periodo),
        "estado_mes": estado_mes,
        "atencion": _atencion(c, comparacion, declarado, diferencias, r["fechas"].get("sire"), hoy or hoy_peru()),
        "hay_datos": r["fechas"].get("sire") is not None,
        "datos_al": min(fechas) if fechas else None,
        "fechas": r["fechas"],
        "igv_por_pagar": r["igv_por_pagar"],
        "saldo_a_favor": r["saldo_a_favor"],
        "renta_porcentaje": r["renta_porcentaje"],
        "renta_regla": r["renta_regla"],
        "renta_por_pagar": r["renta_por_pagar"],
        "casillas": c,
        "lineas_monto": _lineas_monto(c, r),
        "comparacion": comparacion,
        "lineas_igv": lineas_igv,
        "lineas_siguiente": siguiente,
        "lineas_renta": lineas_renta,
        "avisos": r["avisos"],
        "declarado": {
            "num_orden": ultima_declaracion.num_orden,
            "fecha_presentacion": ultima_declaracion.fecha_presentacion,
        } if ultima_declaracion else None,
    }


def guardar_foto(db: Session, empresa_id: str, periodo: str, calculo: dict, fecha: date) -> None:
    """La foto del dia (3.12): recalcular el mismo dia la reemplaza."""
    foto = db.query(LiquidacionCalculo).filter_by(empresa_id=empresa_id, periodo=periodo, fecha=fecha).first()
    if foto is None:
        foto = LiquidacionCalculo(empresa_id=empresa_id, periodo=periodo, fecha=fecha)
        db.add(foto)
    foto.casillas = calculo["casillas"]
    foto.fuentes = {
        "fechas": {k: v.isoformat() if v else None for k, v in calculo["fechas"].items()},
        "renta_porcentaje": calculo["renta_porcentaje"],
        "avisos": calculo["avisos"],
    }
