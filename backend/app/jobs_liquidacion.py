"""
Lecturas de la Liquidacion en vivo (Bloque 1 del piloto). Un solo trabajo por
empresa lee en orden las fuentes pedidas, cada una con su fila en
LiquidacionLectura (estado / etapa / registros / error), asi nunca hay dos
sesiones SOL de la misma empresa a la vez:
  1. declaraciones: los 0621 con sus casillas (Mis Declaraciones y Pagos)
  2. retenciones, percepciones y cuenta de control (una sola sesion del Menu SOL)
  3. aduanas: percepciones de importacion (consulta publica, sin clave)
  4. sire: propuesta de ventas y compras del periodo (API oficial)
Todo es de solo lectura. Cada fuente reemplaza lo guardado en su rango con la
lectura completa de SUNAT. Se piden con el boton "Leer datos de SUNAT" y, cada
madrugada, solas (encolar_liquidacion_automatica, al final).
"""
import logging
import time
from datetime import date, datetime, timedelta, timezone

from app.aduanas_lc import ErrorAduanas, leer_percepciones_importacion
from app.database import SessionLocal
from app.hora_peru import hoy_peru
from app.models import (
    CredencialSol, Empresa, LiquidacionComprobante, LiquidacionCuentaControl, LiquidacionDeclaracion,
    LiquidacionEmpresa, LiquidacionLectura, LiquidacionRetencionPercepcion,
)
from app.rate_limit import adquirir_slot_global, liberar_slot_global
from app.security import descifrar_clave_sol
from app.sire_api import ErrorApiSire, descargar_propuesta, obtener_token

logger = logging.getLogger("app.jobs_liquidacion")

# Orden en que se leen (ver arriba).
FUENTES = ("declaraciones", "retenciones", "percepciones", "cuenta_control", "aduanas", "sire")
FUENTES_SOL = ("retenciones", "percepciones", "cuenta_control")
# Parametro 3.10: historial de 13 meses y, como minimo, desde enero del ano del periodo.
MESES_HISTORIAL = 13
# La cuenta de control muestra como maximo un ano por consulta.
MESES_CUENTA_CONTROL = 12
# Una lectura que sigue "pendiente" o "en_progreso" despues de esto se da por muerta.
VIDA_MAXIMA_LECTURA = timedelta(hours=2)
# El SIRE respondio 429 al pedir varias propuestas seguidas (28/10/2026): una
# por minuto en todo el sistema, por si el limite es por IP y no por empresa.
CLAVE_TURNO_SIRE = "liquidacion:sire:turno"
SEGUNDOS_ENTRE_PEDIDOS_SIRE = 60
ESPERA_MAXIMA_CUPO_SEG = 20 * 60


def sumar_meses(periodo: str, n: int) -> str:
    """("2026-10", -13) -> "2025-09"."""
    total = int(periodo[:4]) * 12 + int(periodo[5:7]) - 1 + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def rango_fuente(fuente: str, periodo: str, hoy: date) -> tuple[str, str]:
    """Periodos ("AAAA-MM") que lee cada fuente para el periodo pedido."""
    if fuente in ("declaraciones", "aduanas"):
        return min(sumar_meses(periodo, -MESES_HISTORIAL), f"{periodo[:4]}-01"), periodo
    if fuente == "cuenta_control":
        # SUNAT solo acepta periodos anteriores al mes en curso.
        hasta = min(sumar_meses(periodo, -1), sumar_meses(hoy.strftime("%Y-%m"), -1))
        return sumar_meses(hasta, -(MESES_CUENTA_CONTROL - 1)), hasta
    return periodo, periodo


def _fechas_del_mes(periodo: str, hoy: date) -> tuple[date, date]:
    """Del dia 1 al ultimo dia del mes (o hasta hoy, si es el mes en curso)."""
    ini = date(int(periodo[:4]), int(periodo[5:7]), 1)
    fin = (ini + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return ini, min(fin, hoy)


def _fecha(iso: str | None) -> date | None:
    try:
        return date.fromisoformat(iso) if iso else None
    except ValueError:
        return None


# --- Guardar lo leido ---

def marcar_vigentes(db, empresa_id: str, periodos: set[str]) -> None:
    """Para cada periodo manda el 0621 presentado al ultimo (parametro CA7)."""
    for periodo in periodos:
        filas = db.query(LiquidacionDeclaracion).filter(
            LiquidacionDeclaracion.empresa_id == empresa_id, LiquidacionDeclaracion.periodo == periodo,
        ).all()
        ultima = max(
            filas,
            key=lambda d: (d.fecha_presentacion or date.min, int(d.num_orden) if d.num_orden.isdigit() else 0),
            default=None,
        )
        for d in filas:
            d.vigente = d is ultima


def aplicar_declaraciones(db, empresa_id: str, declaraciones: list[dict], ahora: datetime) -> int:
    """Alta o actualizacion de cada 0621 por numero de orden. Nunca borra: es el historial."""
    ordenes = [d["num_orden"][:20] for d in declaraciones]
    existentes = {
        d.num_orden: d
        for d in db.query(LiquidacionDeclaracion).filter(
            LiquidacionDeclaracion.empresa_id == empresa_id, LiquidacionDeclaracion.num_orden.in_(ordenes or [""]),
        )
    }
    periodos = set()
    for d, orden in zip(declaraciones, ordenes):
        fila = existentes.get(orden)
        if fila is None:
            fila = LiquidacionDeclaracion(empresa_id=empresa_id, num_orden=orden)
            db.add(fila)
            existentes[orden] = fila
        fila.periodo = d["periodo"][:7]
        fila.rectificatoria = bool(d["rectificatoria"])
        fila.fecha_presentacion = _fecha(d.get("fecha_presentacion"))
        fila.casillas = d["casillas"]
        fila.leido_en = ahora
        periodos.add(fila.periodo)
    db.flush()
    marcar_vigentes(db, empresa_id, periodos)
    return len(existentes)


def aplicar_comprobantes(
    db, empresa_id: str, libro: str, periodo: str, filas: list[dict], ahora: datetime, fuente: str = "propuesta",
) -> int:
    """Reemplaza los comprobantes del libro y periodo por la lectura completa (por CAR SUNAT)."""
    base = db.query(LiquidacionComprobante).filter(
        LiquidacionComprobante.empresa_id == empresa_id,
        LiquidacionComprobante.libro == libro,
        LiquidacionComprobante.fuente == fuente,
    )
    cars = [f["car_sunat"][:40] for f in filas]
    existentes = {c.car_sunat: c for c in base.filter(LiquidacionComprobante.car_sunat.in_(cars or [""]))}
    for f, car in zip(filas, cars):
        fila = existentes.get(car)
        if fila is None:
            fila = LiquidacionComprobante(empresa_id=empresa_id, libro=libro, fuente=fuente, car_sunat=car)
            db.add(fila)
            existentes[car] = fila
        fila.periodo = f["periodo"][:7]
        fila.fecha_emision = _fecha(f.get("fecha_emision"))
        fila.tipo_comprobante = f["tipo_comprobante"][:4]
        fila.serie = f["serie"][:20]
        fila.numero = f["numero"][:20]
        fila.doc_contraparte = f["doc_contraparte"][:15]
        fila.nombre_contraparte = f["nombre_contraparte"][:200]
        for campo in ("base_gravada", "igv", "descuento_base", "descuento_igv", "base_dgng", "igv_dgng",
                      "no_gravado", "exportacion", "total"):
            setattr(fila, campo, f[campo])
        fila.moneda = f["moneda"][:3]
        fila.detraccion = f["detraccion"][:40]
        fila.dam = f["dam"][:40]
        fila.datos = f["datos"]
        fila.leido_en = ahora
    for c in base.filter(LiquidacionComprobante.periodo == periodo):
        if c.car_sunat not in existentes:
            db.delete(c)
    return len(existentes)


def aplicar_retenciones_percepciones(
    db, empresa_id: str, tipo: str, origen: str, filas: list[dict], desde: str, hasta: str, ahora: datetime,
) -> int:
    """Reemplaza las retenciones o percepciones de un origen en los periodos desde..hasta por la lectura completa."""
    base = db.query(LiquidacionRetencionPercepcion).filter(
        LiquidacionRetencionPercepcion.empresa_id == empresa_id,
        LiquidacionRetencionPercepcion.tipo == tipo,
        LiquidacionRetencionPercepcion.origen == origen,
    )
    claves = [(f["ruc_agente"][:15], f["documento"][:40]) for f in filas]
    existentes = {
        (r.ruc_agente, r.documento): r
        for r in base.filter(LiquidacionRetencionPercepcion.documento.in_([d for _, d in claves] or [""]))
    }
    for f, clave in zip(filas, claves):
        fila = existentes.get(clave)
        if fila is None:
            fila = LiquidacionRetencionPercepcion(
                empresa_id=empresa_id, tipo=tipo, origen=origen, ruc_agente=clave[0], documento=clave[1],
            )
            db.add(fila)
            existentes[clave] = fila
        fila.periodo = f["periodo"][:7]
        fila.fecha_emision = _fecha(f.get("fecha_emision"))
        fila.fecha_pago = _fecha(f.get("fecha_pago"))
        fila.monto = f["monto"]
        fila.cuenta = bool(f["cuenta"])
        fila.referencia = (f.get("referencia") or "")[:40]
        fila.leido_en = ahora
    for r in base.filter(LiquidacionRetencionPercepcion.periodo >= desde, LiquidacionRetencionPercepcion.periodo <= hasta):
        if (r.ruc_agente, r.documento) not in existentes:
            db.delete(r)
    return len(set(claves))


def aplicar_cuenta_control(
    db, empresa_id: str, filas: list[dict], grupos: list[tuple[str, str]], desde: str, hasta: str, ahora: datetime,
) -> int:
    """
    Reemplaza, para cada consulta que si se leyo (tipo, RUC del agente), los
    periodos desde..hasta: un periodo que SUNAT ya no lista se borra.
    """
    for tipo, ruc_agente in grupos:
        del_grupo = {f["periodo"]: f for f in filas if f["tipo"] == tipo and f["ruc_agente"] == ruc_agente}
        existentes = {
            c.periodo: c
            for c in db.query(LiquidacionCuentaControl).filter(
                LiquidacionCuentaControl.empresa_id == empresa_id,
                LiquidacionCuentaControl.tipo == tipo,
                LiquidacionCuentaControl.ruc_agente == ruc_agente,
                LiquidacionCuentaControl.periodo >= desde,
                LiquidacionCuentaControl.periodo <= hasta,
            )
        }
        for periodo, f in del_grupo.items():
            fila = existentes.get(periodo)
            if fila is None:
                fila = LiquidacionCuentaControl(empresa_id=empresa_id, periodo=periodo, tipo=tipo, ruc_agente=ruc_agente)
                db.add(fila)
            fila.monto_base = f["monto_base"]
            fila.monto = f["monto"]
            fila.leido_en = ahora
        for periodo, c in existentes.items():
            if periodo not in del_grupo:
                db.delete(c)
    return len(filas)


# --- Crear y ejecutar ---

def lecturas_en_curso(db, empresa_id: str, ahora: datetime) -> list[LiquidacionLectura]:
    return db.query(LiquidacionLectura).filter(
        LiquidacionLectura.empresa_id == empresa_id,
        LiquidacionLectura.estado.in_(("pendiente", "en_progreso")),
        LiquidacionLectura.creado_en >= ahora - VIDA_MAXIMA_LECTURA,
    ).all()


def crear_lecturas(
    db, empresa_id: str, usuario_id: str | None, periodo: str, fuentes: list[str],
    rangos: dict[str, tuple[str, str]] | None = None,
) -> list[LiquidacionLectura]:
    """`rangos`: periodos de alguna fuente distintos de los de rango_fuente (la lectura automatica lee menos historia)."""
    hoy = hoy_peru()
    lecturas = []
    for fuente in sorted(set(fuentes), key=FUENTES.index):
        desde, hasta = (rangos or {}).get(fuente) or rango_fuente(fuente, periodo, hoy)
        lectura = LiquidacionLectura(
            empresa_id=empresa_id, solicitado_por=usuario_id, fuente=fuente,
            periodo_desde=desde, periodo_hasta=hasta, estado="pendiente",
        )
        db.add(lectura)
        lecturas.append(lectura)
    db.flush()
    return lecturas


def encolar_lecturas(lecturas: list[LiquidacionLectura], espera: timedelta | None = None) -> None:
    from app.queue_conn import cola_consultas

    ids = [l.id for l in lecturas]
    if espera:
        cola_consultas.enqueue_in(espera, ejecutar_lecturas_liquidacion, ids, job_timeout="90m")
    else:
        cola_consultas.enqueue(ejecutar_lecturas_liquidacion, ids, job_timeout="90m")


# --- Lectura automatica de cada madrugada (Fase 3, adelantada al piloto) ---
# Parametros 3.1 y 3.2 con un cambio: el Menu SOL iba a las 6:00 a.m., pero a
# esa hora empieza la consulta masiva del buzon (panel maestro) y compiten por
# los mismos cupos de SUNAT. Todo empieza a la 1:30 a.m., un trabajo por
# empresa para el mes que se sigue (periodo_a_seguir):
#   - SIRE y Aduanas (solo el mes): todas las noches.
#   - Retenciones y percepciones: lunes y jueves, y a diario desde 5 dias
#     habiles antes del vencimiento hasta que aparezca el 0621.
#   - 0621: esos mismos dias, mientras falte el del mes anterior.
#   - Cuenta de control: esos mismos dias, si la ultima lectura tiene mas de una semana.
# Mientras se sigue el mes anterior, otro trabajo lee el SIRE y Aduanas del mes
# en curso, para su proyeccion (sin el Menu SOL: no abre otra sesion con la clave).
DIAS_SOL = (0, 3)  # lunes y jueves
DIAS_HABILES_ANTES_DEL_VENCIMIENTO = 5
# Hasta este dia se sigue el mes anterior si su 0621 no aparece (igual que periodosElegibles() del frontend).
DIA_LIMITE_MES_ANTERIOR = 20
DIAS_REFRESCO_CUENTA_CONTROL = 7
# Cada empresa pide 2 propuestas al SIRE, que acepta una por minuto.
ESPACIADO_AUTOMATICO_SEG = 2 * SEGUNDOS_ENTRE_PEDIDOS_SIRE


def dias_habiles_hasta(hoy: date, vence: date) -> int:
    """Dias habiles (lunes a viernes) de hoy al vencimiento: 0 el mismo dia, negativo si ya vencio."""
    paso = 1 if vence >= hoy else -1
    dias, dia = 0, hoy
    while dia != vence:
        dia += timedelta(days=paso)
        if dia.weekday() < 5:
            dias += paso
    return dias


def _declarado(db, empresa_id: str, periodo: str) -> bool:
    return db.query(LiquidacionDeclaracion.id).filter(
        LiquidacionDeclaracion.empresa_id == empresa_id, LiquidacionDeclaracion.periodo == periodo,
    ).first() is not None


def periodo_a_seguir(db, empresa_id: str, hoy: date) -> str:
    """El mes anterior hasta que aparezca su 0621 (o hasta el dia 20); despues, el mes en curso."""
    actual = hoy.strftime("%Y-%m")
    anterior = sumar_meses(actual, -1)
    if hoy.day <= DIA_LIMITE_MES_ANTERIOR and not _declarado(db, empresa_id, anterior):
        return anterior
    return actual


def plan_automatico(db, empresa: Empresa, config: LiquidacionEmpresa, hoy: date) -> tuple[str, dict[str, tuple[str, str]]]:
    """Periodo que sigue la empresa y las fuentes que se leen esta noche, con su rango."""
    from app.calculo_liquidacion import vencimiento

    periodo = periodo_a_seguir(db, empresa.id, hoy)
    fuentes = {"aduanas": (periodo, periodo)}
    if config.api_client_id and config.api_secret_cifrado:
        fuentes["sire"] = (periodo, periodo)
    vence = vencimiento(db, empresa, periodo)
    if hoy.weekday() in DIAS_SOL or (vence and dias_habiles_hasta(hoy, vence) <= DIAS_HABILES_ANTES_DEL_VENCIMIENTO):
        fuentes["retenciones"] = fuentes["percepciones"] = (periodo, periodo)
        if not _declarado(db, empresa.id, sumar_meses(hoy.strftime("%Y-%m"), -1)):
            fuentes["declaraciones"] = (sumar_meses(periodo, -2), periodo)
        desde, hasta = rango_fuente("cuenta_control", periodo, hoy)
        reciente = db.query(LiquidacionLectura.id).filter(
            LiquidacionLectura.empresa_id == empresa.id,
            LiquidacionLectura.fuente == "cuenta_control",
            LiquidacionLectura.estado == "completado",
            LiquidacionLectura.periodo_hasta >= hasta,
            LiquidacionLectura.finalizado_en >= datetime.now(timezone.utc) - timedelta(days=DIAS_REFRESCO_CUENTA_CONTROL),
        ).first()
        if reciente is None:
            fuentes["cuenta_control"] = (desde, hasta)
    return periodo, fuentes


def encolar_liquidacion_automatica(hoy: date | None = None) -> dict:
    """Cada madrugada: uno o dos trabajos por empresa activada, espaciados para respetar el cupo del SIRE."""
    from app.cumplimiento import empresas_de_tenants_activos, filtrar_activas_en_sunat

    hoy = hoy or hoy_peru()
    db = SessionLocal()
    try:
        empresas = (
            filtrar_activas_en_sunat(empresas_de_tenants_activos(db))
            .join(LiquidacionEmpresa, LiquidacionEmpresa.empresa_id == Empresa.id)
            .filter(LiquidacionEmpresa.activa.is_(True))
            .order_by(Empresa.razon_social)
            .all()
        )
        con_clave = {eid for (eid,) in db.query(CredencialSol.empresa_id)}
        actual = hoy.strftime("%Y-%m")
        encoladas, saltadas, trabajos = [], 0, 0
        for empresa in empresas:
            if empresa.id not in con_clave or lecturas_en_curso(db, empresa.id, datetime.now(timezone.utc)):
                saltadas += 1
                continue
            periodo, fuentes = plan_automatico(db, empresa, db.get(LiquidacionEmpresa, empresa.id), hoy)
            del_dia = [(periodo, fuentes)]
            if periodo != actual:
                en_curso = {"aduanas": (actual, actual)}
                if "sire" in fuentes:
                    en_curso["sire"] = (actual, actual)
                del_dia.append((actual, en_curso))
            for p, f in del_dia:
                lecturas = crear_lecturas(db, empresa.id, None, p, list(f), rangos=f)
                db.commit()
                encolar_lecturas(lecturas, espera=timedelta(seconds=trabajos * ESPACIADO_AUTOMATICO_SEG))
                trabajos += 1
            encoladas.append(f"{empresa.ruc} " + " + ".join(f"{p} {','.join(sorted(f))}" for p, f in del_dia))
        logger.info(f"Lectura automatica de liquidacion: {len(encoladas)} empresa(s), {trabajos} trabajo(s), {saltadas} saltada(s)")
        return {"empresas_encoladas": len(encoladas), "trabajos": trabajos, "saltadas": saltadas, "detalle": encoladas}
    finally:
        db.close()


def _esperar_turno_sire(espera_maxima_seg: int = 30 * 60) -> None:
    from app.queue_conn import redis_conn

    inicio = time.time()
    while not redis_conn.set(CLAVE_TURNO_SIRE, "1", nx=True, ex=SEGUNDOS_ENTRE_PEDIDOS_SIRE):
        if time.time() - inicio > espera_maxima_seg:
            raise ErrorApiSire("El SIRE está ocupado con otras lecturas. Intenta de nuevo en unos minutos.")
        time.sleep(5)


def ejecutar_lecturas_liquidacion(lectura_ids: list[str]) -> None:
    db = SessionLocal()

    def _guardar(lectura: LiquidacionLectura, **campos) -> None:
        # La etapa la escribe otra sesion (_reportero): sin refrescar, poner
        # etapa=None no se detecta como cambio y la ultima etapa quedaba.
        db.refresh(lectura)
        for k, v in campos.items():
            setattr(lectura, k, v)
        db.commit()

    def _reportero(lectura_id: str):
        def _reportar(etapa: str | None) -> None:
            db_etapa = SessionLocal()
            try:
                fila = db_etapa.get(LiquidacionLectura, lectura_id)
                if fila:
                    fila.etapa = (etapa or None) and etapa[:30]
                    db_etapa.commit()
            finally:
                db_etapa.close()
        return _reportar

    def _empezar(lectura: LiquidacionLectura) -> None:
        _guardar(lectura, estado="en_progreso", iniciado_en=datetime.now(timezone.utc), etapa=None, error=None)

    def _terminar(lectura: LiquidacionLectura, registros: int) -> None:
        _guardar(lectura, estado="completado", registros_leidos=registros, etapa=None, finalizado_en=datetime.now(timezone.utc))

    def _fallar(lectura: LiquidacionLectura, mensaje: str, registros: int = 0) -> None:
        db.rollback()
        _guardar(
            lectura, estado="error", error=(mensaje or "Error desconocido")[:1000], etapa=None,
            registros_leidos=registros, finalizado_en=datetime.now(timezone.utc),
        )

    try:
        lecturas = {
            l.fuente: l
            for l in db.query(LiquidacionLectura).filter(LiquidacionLectura.id.in_(lectura_ids))
            if l.estado == "pendiente"
        }
        if not lecturas:
            return
        empresa_id = next(iter(lecturas.values())).empresa_id
        empresa = db.get(Empresa, empresa_id)
        credencial = db.query(CredencialSol).filter(CredencialSol.empresa_id == empresa_id).first()
        if empresa is None:
            for l in lecturas.values():
                _fallar(l, "Empresa no encontrada")
            return
        clave = descifrar_clave_sol(credencial.clave_cifrada, credencial.dek_cifrada) if credencial else None
        hoy = hoy_peru()
        # Si SUNAT rechaza la clave no se vuelve a intentar con ella: varios
        # intentos fallidos seguidos pueden bloquear el usuario SOL.
        clave_rechazada = None

        def _sin_clave(lectura) -> bool:
            if credencial is None:
                _fallar(lectura, "La empresa no tiene clave SOL guardada.")
                return True
            if clave_rechazada:
                _fallar(lectura, clave_rechazada)
                return True
            return False

        # 1. Declaraciones 0621
        lectura = lecturas.get("declaraciones")
        if lectura and not _sin_clave(lectura):
            _empezar(lectura)
            try:
                from lectores_liquidacion import leer_declaraciones_0621

                token_slot = adquirir_slot_global(espera_maxima_seg=ESPERA_MAXIMA_CUPO_SEG)
                try:
                    r = leer_declaraciones_0621(
                        ruc=empresa.ruc, usuario_sol=credencial.usuario_sol, clave_sol=clave,
                        razon_social=empresa.razon_social, desde=lectura.periodo_desde, hasta=lectura.periodo_hasta,
                        headless=False, on_progreso=_reportero(lectura.id),
                    )
                finally:
                    liberar_slot_global(token_slot)
                if r["ok"]:
                    _terminar(lectura, aplicar_declaraciones(db, empresa.id, r["declaraciones"], datetime.now(timezone.utc)))
                else:
                    if r.get("credenciales_rechazadas"):
                        clave_rechazada = r["error"]
                    _fallar(lectura, r["error"])
            except Exception as e:
                logger.exception(f"Lectura 0621 {lectura.id}")
                _fallar(lectura, str(e))

        # 2. Menu SOL: retenciones, percepciones y cuenta de control en una sola sesion
        sol = [lecturas[f] for f in FUENTES_SOL if f in lecturas]
        sol = [l for l in sol if not _sin_clave(l)]
        if sol:
            for l in sol:
                _empezar(l)
            try:
                from lectores_liquidacion import leer_menu_sol

                rangos = {}
                for l in sol:
                    rangos[l.fuente] = (
                        (l.periodo_desde, l.periodo_hasta) if l.fuente == "cuenta_control"
                        else _fechas_del_mes(l.periodo_desde, hoy)
                    )
                reporteros = {l.fuente: _reportero(l.id) for l in sol}

                def _reportar_sol(etapa: str | None) -> None:
                    # "leyendo_<fuente>" va a esa fuente; el inicio de sesion, a todas.
                    destino = reporteros.get((etapa or "").removeprefix("leyendo_"))
                    for reportar in ([destino] if destino else reporteros.values()):
                        reportar(etapa)

                token_slot = adquirir_slot_global(espera_maxima_seg=ESPERA_MAXIMA_CUPO_SEG)
                try:
                    r = leer_menu_sol(
                        ruc=empresa.ruc, usuario_sol=credencial.usuario_sol, clave_sol=clave,
                        razon_social=empresa.razon_social, headless=False, on_progreso=_reportar_sol, **rangos,
                    )
                finally:
                    liberar_slot_global(token_slot)
                if not r["ok"]:
                    if r.get("credenciales_rechazadas"):
                        clave_rechazada = r["error"]
                    for l in sol:
                        _fallar(l, r["error"])
                else:
                    ahora = datetime.now(timezone.utc)
                    for l in sol:
                        res = r["resultados"].get(l.fuente) or {"ok": False, "error": "No se leyó", "filas": []}
                        if l.fuente == "cuenta_control":
                            n = aplicar_cuenta_control(
                                db, empresa.id, res["filas"], res.get("grupos") or [], l.periodo_desde, l.periodo_hasta, ahora,
                            )
                            db.commit()
                            if res["ok"]:
                                _terminar(l, n)
                            else:
                                _guardar(l, estado="error", error=(res["error"] or "")[:1000], etapa=None,
                                         registros_leidos=n, finalizado_en=datetime.now(timezone.utc))
                        elif res["ok"]:
                            tipo = "retencion" if l.fuente == "retenciones" else "percepcion"
                            _terminar(l, aplicar_retenciones_percepciones(
                                db, empresa.id, tipo, "comprobante", res["filas"], l.periodo_desde, l.periodo_hasta, ahora,
                            ))
                        else:
                            _fallar(l, res["error"])
            except Exception as e:
                logger.exception(f"Lectura Menu SOL de {empresa.ruc}")
                for l in sol:
                    if l.estado == "en_progreso":
                        _fallar(l, str(e))

        # 3. Aduanas (publica, sin clave)
        lectura = lecturas.get("aduanas")
        if lectura:
            _empezar(lectura)
            try:
                desde = date(int(lectura.periodo_desde[:4]), int(lectura.periodo_desde[5:7]), 1)
                filas = leer_percepciones_importacion(empresa.ruc, desde, _fechas_del_mes(lectura.periodo_hasta, hoy)[1])
                _terminar(lectura, aplicar_retenciones_percepciones(
                    db, empresa.id, "percepcion", "aduanas", filas, lectura.periodo_desde, lectura.periodo_hasta,
                    datetime.now(timezone.utc),
                ))
            except ErrorAduanas as e:
                _fallar(lectura, str(e))
            except Exception as e:
                logger.exception(f"Lectura Aduanas {lectura.id}")
                _fallar(lectura, str(e))

        # 4. SIRE por la API oficial
        lectura = lecturas.get("sire")
        if lectura and not _sin_clave(lectura):
            _empezar(lectura)
            config = db.get(LiquidacionEmpresa, empresa.id)
            leidos = 0
            try:
                if config is None or not config.api_client_id or not config.api_secret_cifrado:
                    raise ErrorApiSire("Faltan las credenciales de la API del SIRE.")
                token = obtener_token(
                    config.api_client_id, descifrar_clave_sol(config.api_secret_cifrado, config.api_dek_cifrada),
                    empresa.ruc, credencial.usuario_sol, clave,
                )
                # Varios meses: el historial de compras de la revision de compras (Fase 5), un mes a la vez.
                periodo = lectura.periodo_desde
                while periodo <= lectura.periodo_hasta:
                    for libro, etapa in (("RVIE", "leyendo_ventas"), ("RCE", "leyendo_compras")):
                        _reportero(lectura.id)("esperando_turno_sire")
                        _esperar_turno_sire()
                        _reportero(lectura.id)(etapa)
                        filas = descargar_propuesta(token, libro, periodo)
                        leidos += aplicar_comprobantes(db, empresa.id, libro, periodo, filas, datetime.now(timezone.utc))
                        db.commit()
                    periodo = sumar_meses(periodo, 1)
                _terminar(lectura, leidos)
            except ErrorApiSire as e:
                _fallar(lectura, str(e), leidos)
            except Exception as e:
                logger.exception(f"Lectura SIRE {lectura.id}")
                _fallar(lectura, str(e), leidos)

        logger.info(f"Lecturas de liquidacion de {empresa.ruc}: " + ", ".join(f"{l.fuente}={l.estado}" for l in lecturas.values()))

        # 5. Foto del calculo con los datos nuevos (Bloque 2). Una falla aca no ensucia las lecturas.
        try:
            from app.calculo_liquidacion import calcular_periodo, guardar_foto

            periodo = max(l.periodo_hasta for l in lecturas.values())
            guardar_foto(db, empresa.id, periodo, calcular_periodo(db, empresa, periodo), hoy_peru())
            db.commit()
        except Exception:
            logger.exception(f"Calculo de liquidacion de {empresa.ruc}")
            db.rollback()
    except Exception:
        logger.exception(f"Error en las lecturas de liquidacion {lectura_ids}")
        db.rollback()
        for l in db.query(LiquidacionLectura).filter(
            LiquidacionLectura.id.in_(lectura_ids), LiquidacionLectura.estado.in_(("pendiente", "en_progreso")),
        ):
            l.estado, l.error, l.finalizado_en = "error", "Error inesperado en la lectura", datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
