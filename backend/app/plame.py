"""
Obligacion de presentar la PLAME (formulario 0601) de cada empresa.

Una empresa esta obligada si (en este orden):
1. Se marco a mano "no esta obligada" (obligacion de planilla apagada y
   ninguna activa): NO, aunque SUNAT tenga historial.
2. Presento un 0601 en SUNAT: desde su primer periodo presentado.
3. Recibio recibos por honorarios vigentes (rentas de cuarta categoria):
   desde el primer periodo con recibos. Los lee la revision semanal
   (ver scheduler_job.encolar_rxh_semanal) de Menu SOL > Consulta Receptor.
4. Tiene la obligacion activa (casilla al registrar, o detectada por 2 o 3):
   siempre ("0000-00").

El periodo de un recibo es el mes de su FECHA DE EMISION (es lo que filtra
SUNAT). En la PLAME la renta de cuarta se declara por fecha de pago, asi que
un recibo emitido a fin de mes y pagado al siguiente puede adelantar el
aviso un mes: se prefiere avisar de mas a perder un caso.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DeclaracionSunat, EmpresaObligacion, ReciboHonorario

SIEMPRE = "0000-00"
TIPO_RECIBO_HONORARIOS = "RH"
ESTADO_RECIBO_VIGENTE = "NO ANULADO"


def recibos_vigentes(query):
    """Solo recibos por honorarios no anulados ni revertidos: los que obligan a la PLAME."""
    return query.filter(ReciboHonorario.tipo == TIPO_RECIBO_HONORARIOS, ReciboHonorario.estado == ESTADO_RECIBO_VIGENTE)


def periodo_rxh_a_revisar(hoy: date) -> str:
    """El periodo cuya PLAME vence este mes: el mes anterior."""
    anterior = hoy.replace(day=1) - timedelta(days=1)
    return f"{anterior.year}-{anterior.month:02d}"


def rango_del_periodo(periodo: str) -> tuple[date, date]:
    anio, mes = int(periodo[:4]), int(periodo[5:7])
    inicio = date(anio, mes, 1)
    fin = (date(anio + (mes == 12), mes % 12 + 1, 1)) - timedelta(days=1)
    return inicio, fin


def plame_desde(db: Session, empresa_ids: list[str]) -> dict[str, str | None]:
    """Por empresa: desde que periodo debe presentar la PLAME ("YYYY-MM", SIEMPRE) o None si no esta obligada."""
    if not empresa_ids:
        return {}
    activas, apagadas = set(), set()
    for eid, activa in db.query(EmpresaObligacion.empresa_id, EmpresaObligacion.activa).filter(
        EmpresaObligacion.empresa_id.in_(empresa_ids),
        EmpresaObligacion.tipo == "planilla",
        EmpresaObligacion.regla_vencimiento == "cronograma_sunat",
    ):
        (activas if activa else apagadas).add(eid)
    apagadas -= activas
    primer_0601 = dict(
        db.query(DeclaracionSunat.empresa_id, func.min(DeclaracionSunat.periodo))
        .filter(DeclaracionSunat.empresa_id.in_(empresa_ids), DeclaracionSunat.formulario == "0601")
        .group_by(DeclaracionSunat.empresa_id)
    )
    primer_rxh = dict(
        recibos_vigentes(db.query(ReciboHonorario.empresa_id, func.min(ReciboHonorario.periodo)))
        .filter(ReciboHonorario.empresa_id.in_(empresa_ids))
        .group_by(ReciboHonorario.empresa_id)
    )
    resultado = {}
    for eid in empresa_ids:
        if eid in apagadas:
            resultado[eid] = None
            continue
        desde = min((p for p in (primer_0601.get(eid), primer_rxh.get(eid)) if p), default=None)
        resultado[eid] = desde or (SIEMPRE if eid in activas else None)
    return resultado


def resumen_rxh(db: Session, empresa_ids: list[str], anio: int) -> dict[str, dict[str, dict]]:
    """Por empresa y periodo del anio: cantidad, renta bruta y retencion de los recibos vigentes."""
    resumen: dict[str, dict[str, dict]] = {}
    if not empresa_ids:
        return resumen
    for eid, periodo, cantidad, bruta, retencion in (
        recibos_vigentes(
            db.query(
                ReciboHonorario.empresa_id, ReciboHonorario.periodo, func.count(ReciboHonorario.id),
                func.sum(ReciboHonorario.renta_bruta), func.sum(ReciboHonorario.retencion),
            )
        )
        .filter(ReciboHonorario.empresa_id.in_(empresa_ids), ReciboHonorario.periodo.like(f"{anio}-%"))
        .group_by(ReciboHonorario.empresa_id, ReciboHonorario.periodo)
    ):
        resumen.setdefault(eid, {})[periodo] = {
            "cantidad": cantidad, "renta_bruta": round(bruta or 0, 2), "retencion": round(retencion or 0, 2),
        }
    return resumen


def aplicar_lectura_rxh(db: Session, empresa_id: str, periodo: str, recibos: list[dict], ahora: datetime) -> int:
    """Deja en la base exactamente los recibos que SUNAT lista para ese periodo. No hace commit."""
    existentes = {
        (r.doc_emisor, r.tipo, r.numero): r
        for r in db.query(ReciboHonorario).filter(ReciboHonorario.empresa_id == empresa_id, ReciboHonorario.periodo == periodo)
    }
    vistos = set()
    for dato in recibos:
        clave = (dato["doc_emisor"], dato["tipo"], dato["numero"])
        if clave in vistos:
            continue
        vistos.add(clave)
        fila = existentes.get(clave)
        if fila is None:
            # Un recibo puede haber quedado en otro periodo si SUNAT cambio su fecha: se mueve.
            fila = db.query(ReciboHonorario).filter(
                ReciboHonorario.empresa_id == empresa_id, ReciboHonorario.doc_emisor == clave[0],
                ReciboHonorario.tipo == clave[1], ReciboHonorario.numero == clave[2],
            ).first() or ReciboHonorario(empresa_id=empresa_id, doc_emisor=clave[0], tipo=clave[1], numero=clave[2])
            db.add(fila)
        fila.periodo = periodo
        fila.fecha_emision = date.fromisoformat(dato["fecha_emision"]) if dato.get("fecha_emision") else None
        fila.estado = dato["estado"]
        fila.nombre_emisor = (dato.get("nombre_emisor") or "")[:200]
        fila.moneda = dato.get("moneda") or ""
        for campo in ("renta_bruta", "retencion", "renta_neta", "pendiente_pago"):
            setattr(fila, campo, dato.get(campo) or 0)
        fila.actualizado_en = ahora
    for clave, fila in existentes.items():
        if clave not in vistos:
            db.delete(fila)
    return len(vistos)
