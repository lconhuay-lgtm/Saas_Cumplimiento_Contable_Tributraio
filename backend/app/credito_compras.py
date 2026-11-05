"""
Revision de compras y credito fiscal (Fase 5 de la Liquidacion en vivo).

Cada compra del Registro de Compras del SIRE (la propuesta) se cruza con los
depositos de detraccion que la empresa hizo como adquiriente (DetraccionPago)
por RUC del proveedor, serie y numero (5.6). Reglas confirmadas por el
contador el 05/11/2026:

- El deposito vence el 5.o dia habil del mes siguiente al de la anotacion de
  la compra (el periodo en que aparece en el registro).
- Depositado a tiempo: el IGV cuenta en el mes de la anotacion. Depositado
  tarde: cuenta desde el mes del deposito. No depositado: no cuenta.
- La detraccion es en soles enteros.

Lleva detraccion (en este orden): lo que decidio el responsable; una regla
"siempre lleva detraccion" del proveedor; un deposito que la cruza; la marca
"D" del SIRE. Si no, "Por verificar" cuando es de S/ 700 o mas y el
proveedor ya tuvo depositos (5.5).

Una compra sin deposito con el plazo vencido solo se da por "no depositada"
si las detracciones de la empresa ya se leyeron hasta el plazo; si no, sigue
"en riesgo". Lo que cuenta en el mes reemplaza al IGV de compras del
registro en el calculo (casilla 178).
"""
import html
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.detracciones_spot import (
    TOLERANCIA_SOLES, descripcion, habiles_hasta, monto_minimo, plazo_deposito, tasa,
)
from app.jobs_liquidacion import sumar_meses
from app.models import (
    DetraccionCobertura, DetraccionPago, LiquidacionComprobante, LiquidacionCompraDecision, LiquidacionReglaProveedor,
    Usuario,
)

TIPOS_IMPORTACION = ("50", "52", "53", "54")
TIPOS_NOTA_CREDITO = ("07", "87", "97")
MESES_ATRAS = 12
# Avisos de detraccion por vencer (5.14): desde 5 dias habiles antes del plazo.
DIAS_AVISO = 5

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "setiembre", "octubre",
         "noviembre", "diciembre")

# Grupos de los filtros del boceto (pantalla 3).
GRUPOS = {
    "pagada": "Detracción pagada", "por_depositar": "Con plazo para depositar", "vencida": "No depositada",
    "verificar": "Por verificar", "excluido": "Excluidos a mano", "no_sujeta": "Sin detracción",
}
MOTIVOS = (
    "Gasto no deducible", "No relacionado con el negocio", "Comprobante observado o con error",
    "Detracción depositada (constancia en mano)", "Otro",
)


def nombre_mes(periodo: str) -> str:
    return MESES[int(periodo[5:7]) - 1]


def _clave(ruc: str, serie: str, numero: str) -> tuple[str, str, str]:
    return (ruc or "").strip(), (serie or "").strip().upper(), (numero or "").strip().lstrip("0")


def _soles(monto: float) -> str:
    return f"S/ {round(monto or 0):,}"


@dataclass
class _Deposito:
    constancia: str
    fecha: date | None
    monto: float
    codigo: str


class RevisionCompras:
    """Lo que hace falta para clasificar las compras de una empresa, leido una vez."""

    def __init__(self, db: Session, empresa_id: str, ruc: str, hoy: date):
        self.db, self.empresa_id, self.hoy = db, empresa_id, hoy
        self.depositos: dict[tuple, list[_Deposito]] = {}
        self.por_numero: dict[tuple, list[tuple]] = {}
        self.codigo_proveedor: dict[str, str] = {}
        for d in (
            db.query(DetraccionPago)
            .filter(DetraccionPago.empresa_id == empresa_id, DetraccionPago.doc_adquiriente == ruc)
            .order_by(DetraccionPago.fecha_pago)
        ):
            clave = _clave(d.ruc_proveedor, d.serie, d.numero)
            self.depositos.setdefault(clave, []).append(_Deposito(d.num_constancia, d.fecha_pago, d.monto, d.tipo_bien))
            self.por_numero.setdefault((clave[0], clave[2]), []).append(clave)
            if d.tipo_bien:
                self.codigo_proveedor[clave[0]] = d.tipo_bien
        cobertura = db.get(DetraccionCobertura, empresa_id)
        self.detracciones_al = cobertura.hasta if cobertura else None
        self.decisiones: dict[str, LiquidacionCompraDecision] = {}
        for d in (
            db.query(LiquidacionCompraDecision)
            .filter(LiquidacionCompraDecision.empresa_id == empresa_id)
            .order_by(LiquidacionCompraDecision.creado_en)
        ):
            self.decisiones[d.car_sunat] = d
        self.reglas = (
            db.query(LiquidacionReglaProveedor)
            .filter(LiquidacionReglaProveedor.empresa_id == empresa_id, LiquidacionReglaProveedor.activa.is_(True))
            .order_by(LiquidacionReglaProveedor.creado_en)
            .all()
        )
        self._nombres: dict[str, str] = {}

    def _nombre_usuario(self, usuario_id: str | None) -> str:
        if not usuario_id:
            return ""
        if usuario_id not in self._nombres:
            u = self.db.get(Usuario, usuario_id)
            self._nombres[usuario_id] = (" ".join(p for p in (u.nombre, u.apellidos) if p) or u.email) if u else ""
        return self._nombres[usuario_id]

    def _regla(self, ruc: str, periodo: str, regla: str) -> LiquidacionReglaProveedor | None:
        return next((r for r in reversed(self.reglas) if r.ruc_proveedor == ruc and r.regla == regla and r.desde_periodo <= periodo), None)

    def _depositos_de(self, compra) -> tuple[list[_Deposito], bool]:
        """Depositos de la compra y si la coincidencia es dudosa (solo coincide el numero, no la serie)."""
        clave = _clave(compra.doc_contraparte, compra.serie, compra.numero)
        if clave in self.depositos:
            return self.depositos[clave], False
        otras = set(self.por_numero.get((clave[0], clave[2]), []))
        if len(otras) == 1:
            return self.depositos[otras.pop()], True
        return [], False

    def clasificar(self, compra: LiquidacionComprobante) -> dict:
        periodo = compra.periodo
        igv = (compra.igv or 0) + (compra.igv_dgng or 0)
        ruc = (compra.doc_contraparte or "").strip()
        decision = self.decisiones.get(compra.car_sunat)
        regla_lleva = self._regla(ruc, periodo, "lleva_detraccion")
        regla_excluir = self._regla(ruc, periodo, "excluir")
        depositos, dudosa = self._depositos_de(compra)
        plazo = plazo_deposito(periodo)
        fila = {
            "car": compra.car_sunat, "periodo": periodo, "fecha_emision": compra.fecha_emision,
            "tipo_comprobante": compra.tipo_comprobante, "serie": compra.serie, "numero": compra.numero,
            "ruc": ruc, "proveedor": html.unescape(compra.nombre_contraparte or ""), "total": round(compra.total or 0, 2), "igv": round(igv, 2),
            "marca_sire": bool((compra.detraccion or "").strip()), "plazo": plazo, "codigo": None, "descripcion_codigo": "",
            "tasa": None, "esperado": None, "depositado": None,
            "depositos": [{"constancia": d.constancia, "fecha": d.fecha, "monto": d.monto} for d in depositos],
            "decision": None, "regla": None,
        }
        if decision:
            fila["decision"] = {
                "lleva": decision.lleva, "credito": decision.credito, "motivo": decision.motivo,
                "comentario": decision.comentario, "constancia": decision.constancia,
                "usuario_nombre": self._nombre_usuario(decision.usuario_id), "fecha": decision.creado_en,
            }
        regla = regla_excluir or regla_lleva
        if regla:
            fila["regla"] = {"id": regla.id, "regla": regla.regla, "desde_periodo": regla.desde_periodo,
                             "usuario_nombre": self._nombre_usuario(regla.usuario_id)}

        # 1. Lleva detraccion?
        lleva_decidido = decision.lleva if decision and decision.lleva != "auto" else None
        if compra.tipo_comprobante in TIPOS_IMPORTACION:
            lleva, por_que = "no", "IGV pagado en aduanas"
        elif compra.tipo_comprobante in TIPOS_NOTA_CREDITO or igv <= 0:
            lleva, por_que = "no", "Nota de crédito" if compra.tipo_comprobante in TIPOS_NOTA_CREDITO else "Sin IGV"
        elif lleva_decidido == "no":
            lleva, por_que = "no", "Marcada sin detracción por el responsable"
        elif lleva_decidido == "si":
            lleva, por_que = "si", "Marcada con detracción por el responsable"
        elif regla_lleva:
            lleva, por_que = "si", "Proveedor marcado: siempre con detracción"
        elif depositos:
            lleva, por_que = "si", "Tiene depósito de detracción"
        elif fila["marca_sire"]:
            lleva, por_que = "si", "Marcada con detracción en el SIRE"
        elif (compra.total or 0) >= monto_minimo(self.codigo_proveedor.get(ruc)) and ruc in self.codigo_proveedor:
            lleva, por_que = "verificar", f"{_soles(compra.total)} de un proveedor con detracciones anteriores"
        else:
            lleva = "no"
            por_que = f"Menos de {_soles(monto_minimo(None))}" if (compra.total or 0) < monto_minimo(None) else "Sin marca de detracción"

        codigo = depositos[0].codigo if depositos else self.codigo_proveedor.get(ruc)
        if lleva != "no" and codigo:
            fila["codigo"], fila["descripcion_codigo"], fila["tasa"] = codigo, descripcion(codigo), tasa(codigo)
            if fila["tasa"]:
                fila["esperado"] = round((compra.total or 0) * fila["tasa"])
        texto_tasa = f"{fila['tasa'] * 100:g} % · " if fila["tasa"] else ""

        # 2. Estado de la detraccion
        credito_periodo = periodo
        if lleva == "no":
            estado, badge, nota = "no_sujeta", "No sujeta", por_que
            credito, credito_texto, credito_nota = "cuenta", "Cuenta", ""
        elif lleva == "verificar":
            estado, badge, nota = "verificar", "Verificar si lleva", por_que
            credito, credito_texto, credito_nota = "por_confirmar", "Cuenta (por confirmar)", "Confirma si lleva detracción"
        elif depositos:
            depositado = sum(d.monto for d in depositos)
            fecha = max((d.fecha for d in depositos if d.fecha), default=None)
            fila["depositado"] = round(depositado, 2)
            constancias = ", ".join(d.constancia for d in depositos)
            if dudosa or (fila["esperado"] and depositado + TOLERANCIA_SOLES < fila["esperado"]):
                estado, badge = "verificar", "Coincidencia dudosa"
                nota = (f"Depósito {_soles(depositado)} de {_soles(fila['esperado'])} esperados · constancia {constancias}"
                        if not dudosa else f"El depósito coincide en número pero no en serie · constancia {constancias}")
                credito, credito_texto, credito_nota = "por_confirmar", "Cuenta (por confirmar)", "Revisa el depósito"
            elif fecha is None or fecha <= plazo:
                estado, badge = "pagada", "Pagada a tiempo"
                nota = f"Constancia {constancias}" + (f" · depositada el {fecha:%d/%m}" if fecha else "")
                credito, credito_texto, credito_nota = "cuenta", "Cuenta", "Detracción depositada dentro del plazo"
            else:
                credito_periodo = fecha.strftime("%Y-%m")
                estado, badge = "pagada", "Pagada tarde"
                nota = f"Venció el {plazo:%d/%m} · depositada el {fecha:%d/%m}"
                credito, credito_texto = "pasa", f"Cuenta en {nombre_mes(credito_periodo)}"
                credito_nota = "El crédito pasa al mes del depósito"
        elif decision and decision.constancia:
            estado, badge = "pagada", "Según constancia"
            nota = f"Constancia {decision.constancia} (la indicó el responsable; falta que SUNAT la muestre)"
            credito, credito_texto, credito_nota = "cuenta", "Cuenta", "Depositada según constancia"
        elif self.hoy <= plazo:
            estado, badge = "por_depositar", "Por depositar"
            nota = f"{texto_tasa}{_soles(fila['esperado']) + ' · ' if fila['esperado'] else ''}plazo hasta el {plazo:%d/%m}"
            credito, credito_texto = "en_riesgo", "Cuenta si depositas a tiempo"
            credito_nota = por_que
        elif self.detracciones_al is None or self.detracciones_al < plazo:
            estado, badge = "por_depositar", "Sin confirmar"
            leidas = f"las detracciones se leyeron hasta el {self.detracciones_al:%d/%m}" if self.detracciones_al else "aún no se leen las detracciones"
            nota = f"Venció el {plazo:%d/%m}; {leidas}"
            credito, credito_texto, credito_nota = "en_riesgo", "Cuenta si se depositó a tiempo", por_que
        else:
            credito_periodo = None
            estado, badge = "vencida", "No depositada · vencida"
            nota = f"{texto_tasa}{_soles(fila['esperado']) + ' · ' if fila['esperado'] else ''}venció el {plazo:%d/%m}"
            credito, credito_texto, credito_nota = "suspendido", "Suspendido", "Contará en el mes en que se deposite"

        # 3. Decision sobre el credito (manda sobre lo automatico)
        fila["credito_automatico"] = credito_texto
        if decision and decision.credito == "excluir":
            credito, credito_texto, credito_periodo = "excluido", "Excluido a mano", None
            credito_nota = " · ".join(x for x in (decision.motivo, fila["decision"]["usuario_nombre"], f"{decision.creado_en:%d/%m}") if x)
        elif regla_excluir and not (decision and decision.credito == "incluir"):
            credito, credito_texto, credito_periodo = "excluido", "Excluido a mano", None
            credito_nota = f"Proveedor excluido siempre{': ' + regla_excluir.motivo if regla_excluir.motivo else ''}"
        elif decision and decision.credito == "incluir":
            credito, credito_texto, credito_periodo = "cuenta", "Incluido a mano", periodo
            credito_nota = " · ".join(x for x in (decision.motivo, fila["decision"]["usuario_nombre"], f"{decision.creado_en:%d/%m}") if x)

        fila.update({
            "estado": estado, "grupo": "excluido" if credito == "excluido" else estado, "detraccion_texto": badge,
            "detraccion_nota": nota, "credito": credito, "credito_texto": credito_texto, "credito_nota": credito_nota,
            "credito_periodo": credito_periodo, "lleva": lleva,
        })
        return fila

    def _anteriores(self, periodo: str) -> list[LiquidacionComprobante]:
        """Compras de los 12 meses anteriores que pueden pesar en el periodo: con alguna senal de detraccion."""
        rucs = set(self.codigo_proveedor) | {r.ruc_proveedor for r in self.reglas}
        cars = [car for car, d in self.decisiones.items() if d.lleva == "si" or d.constancia]
        senales = [LiquidacionComprobante.detraccion != ""]
        if rucs:
            senales.append(LiquidacionComprobante.doc_contraparte.in_(rucs))
        if cars:
            senales.append(LiquidacionComprobante.car_sunat.in_(cars))
        return self.db.query(LiquidacionComprobante).filter(
            LiquidacionComprobante.empresa_id == self.empresa_id,
            LiquidacionComprobante.libro == "RCE",
            LiquidacionComprobante.fuente == "propuesta",
            LiquidacionComprobante.periodo >= sumar_meses(periodo, -MESES_ATRAS),
            LiquidacionComprobante.periodo < periodo,
            or_(*senales),
        ).all()

    def del_periodo(self, periodo: str, compras: list[LiquidacionComprobante]) -> dict:
        """
        Las compras del periodo y las de meses anteriores que pesan en el: las
        depositadas tarde cuyo credito pasa a este mes, las suspendidas y las
        que todavia estan en plazo. `ajuste` es lo que cambia el IGV de compras
        del registro; `movimientos` lo mismo por fecha, para el grafico dia a dia.
        """
        filas = [self.clasificar(c) for c in compras]
        registro = sum(f["igv"] for f in filas)
        movimientos = []
        for f in filas:
            if f["credito_periodo"] != periodo:
                movimientos.append((f["fecha_emision"], -f["igv"]))
        for c in self._anteriores(periodo):
            f = self.clasificar(c)
            if f["credito_periodo"] == periodo and f["credito"] in ("pasa", "cuenta") and f["estado"] == "pagada":
                f["credito_texto"] = f"Cuenta (viene de {nombre_mes(c.periodo)})"
                fecha = max((d["fecha"] for d in f["depositos"] if d["fecha"]), default=None)
                movimientos.append((fecha, f["igv"]))
                filas.append(f)
            elif f["credito"] in ("suspendido", "en_riesgo"):
                filas.append(f)

        def suma(cond):
            return round(sum(f["igv"] for f in filas if cond(f)))

        cuenta = suma(lambda f: f["credito_periodo"] == periodo and f["credito"] in ("cuenta", "pasa", "por_confirmar"))
        viene = suma(lambda f: f["periodo"] != periodo and f["credito_periodo"] == periodo)
        en_riesgo = [f for f in filas if f["credito"] == "en_riesgo" and f["periodo"] == periodo]
        suspendidas = [f for f in filas if f["credito"] == "suspendido"]
        grupos = {g: sum(1 for f in filas if f["grupo"] == g) for g in GRUPOS}
        filas.sort(key=lambda f: (
            ("por_depositar", "vencida", "verificar", "pagada", "excluido", "no_sujeta").index(f["grupo"]),
            -(f["igv"] or 0),
        ))
        return {
            "periodo": periodo,
            "filas": filas,
            "grupos": [{"clave": g, "nombre": n, "cantidad": grupos[g]} for g, n in GRUPOS.items()],
            "resumen": {
                "credito_cuenta": cuenta,
                "credito_viene": viene,
                "en_riesgo": round(sum(f["igv"] for f in en_riesgo)),
                "en_riesgo_cantidad": len(en_riesgo),
                "en_riesgo_plazo": min((f["plazo"] for f in en_riesgo), default=None),
                "suspendido": round(sum(f["igv"] for f in suspendidas)),
                "suspendido_cantidad": len(suspendidas),
                "por_verificar": grupos["verificar"],
                "excluido": suma(lambda f: f["credito"] == "excluido"),
                "registro": round(registro),
            },
            # Lo que cuenta en el mes (incluido lo que aun esta en plazo) menos el IGV del registro.
            "ajuste": sum(m for _, m in movimientos),
            "movimientos": movimientos,
            "detracciones_al": self.detracciones_al,
        }

    def alertas(self, revision: dict) -> list[str]:
        """Avisos de la plataforma (5.14): detracciones por vencer en 5 dias habiles o menos, y vencidas."""
        motivos = []
        por_vencer: dict[date, list[dict]] = {}
        for f in revision["filas"]:
            if f["credito"] == "en_riesgo" and f["estado"] == "por_depositar" and f["plazo"] >= self.hoy:
                if habiles_hasta(self.hoy, f["plazo"]) <= DIAS_AVISO:
                    por_vencer.setdefault(f["plazo"], []).append(f)
        for plazo, filas in sorted(por_vencer.items()):
            faltan = habiles_hasta(self.hoy, plazo)
            cuando = "vence hoy" if faltan == 0 else f"falta{'n' if faltan > 1 else ''} {faltan} día{'s' if faltan > 1 else ''} hábil{'es' if faltan > 1 else ''}"
            motivos.append(
                f"Detracción por depositar: {len(filas)} factura(s), {_soles(sum(f['igv'] for f in filas))} de crédito en riesgo; "
                f"plazo hasta el {plazo:%d/%m} ({cuando})"
            )
        vencidas = [f for f in revision["filas"] if f["credito"] == "suspendido"]
        if vencidas:
            motivos.append(
                f"Detracción no depositada: {len(vencidas)} factura(s), crédito suspendido {_soles(sum(f['igv'] for f in vencidas))}"
            )
        return motivos
