"""
Disparadores manuales del chequeo nocturno, el resumen diario, y la
reclasificacion de mensajes -- mas el panel de salud del sistema (Fase 3,
semana 9): disparar el chequeo canario a mano, y ver de un vistazo la tasa
de exito reciente (desglosada por flujo detectado) y los ultimos errores,
tanto del canario como de las consultas normales.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Usuario, MensajeBuzon, CanarioCheck, ConsultaJob, Empresa
from app.deps import get_usuario_actual, get_staff_actual
from app.scheduler_job import (
    encolar_chequeo_nocturno,
    enviar_resumenes_diarios,
    ejecutar_chequeo_canario,
    redis_conn,
    _CLAVE_REDIS_CANARIO_EN_ALERTA,
)
from app.clasificacion import clasificar_tipo
from app.schemas import (
    SaludResponse,
    SaludCanarioResumen,
    SaludCanarioPorFlujo,
    SaludConsultasResumen,
    ErrorRecienteItem,
    DocumentoRecienteItem,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def _con_utc(momento):
    # Mismo ajuste que en dashboard.py: SQLite (pruebas) devuelve datetimes
    # "naive" aunque la columna sea DateTime(timezone=True); Postgres
    # (produccion) los devuelve con tzinfo. Sin esto, comparar/restar un
    # naive con uno aware revienta con TypeError.
    if momento is not None and momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


@router.post("/chequeo-nocturno")
def disparar_chequeo_nocturno(
    espaciado_seg: int = 45,
    usuario: Usuario = Depends(get_staff_actual),
):
    return encolar_chequeo_nocturno(espaciado_seg=espaciado_seg)


@router.post("/enviar-resumenes")
def disparar_resumenes(
    horas_atras: int = 12,
    usuario: Usuario = Depends(get_staff_actual),
):
    return enviar_resumenes_diarios(horas_atras=horas_atras)


@router.post("/reclasificar-mensajes")
def reclasificar_mensajes(
    usuario: Usuario = Depends(get_staff_actual),
    db: Session = Depends(get_db),
):
    mensajes = db.query(MensajeBuzon).all()
    actualizados = 0
    for m in mensajes:
        nuevo_tipo = clasificar_tipo(m.asunto)
        if m.tipo != nuevo_tipo:
            m.tipo = nuevo_tipo
            actualizados += 1
    db.commit()
    return {"mensajes_revisados": len(mensajes), "mensajes_actualizados": actualizados}


@router.post("/canario/ejecutar")
def disparar_chequeo_canario(
    usuario: Usuario = Depends(get_staff_actual),
):
    """Corre el chequeo canario ahora mismo, sin esperar al intervalo programado (ver scheduler_entry.py)."""
    return ejecutar_chequeo_canario()


@router.get("/salud", response_model=SaludResponse)
def obtener_salud(
    horas_atras: int = 24 * 7,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Fase 3 (semana 9): panel simple de salud. Junta dos cosas por separado
    a proposito -- el canario (login de prueba dedicado, no afecta datos de
    tenants) y las consultas normales (lo que de verdad usan los clientes)
    -- porque pueden fallar por razones distintas y mezclarlas escondería
    cual de las dos esta realmente rota.

    Filtrado por tenant_id en ambas queries (fix Fase R1): antes devolvia
    canario_checks y consultas_jobs de TODOS los tenants sin filtrar, asi
    que cualquier usuario logueado veia metricas agregadas de otros
    estudios contables. Efecto colateral esperado: solo el tenant dueño de
    la empresa marcada es_canario vera datos de canario aqui -- correcto,
    porque ese chequeo es una cuenta de prueba interna, no un dato de
    cliente que deba ser publico entre tenants.
    """
    desde = datetime.now(timezone.utc) - timedelta(hours=horas_atras)

    tiene_empresa_canario = (
        db.query(Empresa.id)
        .filter(Empresa.es_canario.is_(True), Empresa.tenant_id == usuario.tenant_id)
        .first()
        is not None
    )

    checks = (
        db.query(CanarioCheck)
        .join(Empresa, Empresa.id == CanarioCheck.empresa_id)
        .filter(CanarioCheck.ejecutado_en >= desde, Empresa.tenant_id == usuario.tenant_id)
        .order_by(CanarioCheck.ejecutado_en.desc())
        .all()
    )

    por_flujo_acc: dict[str, dict] = {}
    for c in checks:
        clave = c.flujo_detectado or "desconocido"
        acc = por_flujo_acc.setdefault(clave, {"total": 0, "exitosos": 0, "duraciones": []})
        acc["total"] += 1
        if c.exito:
            acc["exitosos"] += 1
        if c.duracion_seg is not None:
            acc["duraciones"].append(c.duracion_seg)

    por_flujo = [
        SaludCanarioPorFlujo(
            flujo=flujo,
            total=acc["total"],
            exitosos=acc["exitosos"],
            tasa_exito=round(acc["exitosos"] / acc["total"], 3) if acc["total"] else 0.0,
            duracion_prom_seg=(
                round(sum(acc["duraciones"]) / len(acc["duraciones"]), 2) if acc["duraciones"] else None
            ),
        )
        for flujo, acc in sorted(por_flujo_acc.items())
    ]

    canario = SaludCanarioResumen(
        tiene_empresa_canario=tiene_empresa_canario,
        en_alerta=redis_conn.get(_CLAVE_REDIS_CANARIO_EN_ALERTA) is not None,
        total_checks=len(checks),
        ultimo_check_en=_con_utc(checks[0].ejecutado_en) if checks else None,
        ultimo_resultado=checks[0].exito if checks else None,
        por_flujo=por_flujo,
    )

    jobs = (
        db.query(ConsultaJob)
        .join(Empresa, Empresa.id == ConsultaJob.empresa_id)
        .filter(
            Empresa.tenant_id == usuario.tenant_id,
            ConsultaJob.estado.in_(["completado", "error"]),
            ConsultaJob.finalizado_en.isnot(None),
            ConsultaJob.finalizado_en >= desde,
        )
        .all()
    )
    exitosas = sum(1 for j in jobs if j.estado == "completado")
    fallidas = sum(1 for j in jobs if j.estado == "error")
    duraciones_jobs = [
        (_con_utc(j.finalizado_en) - _con_utc(j.iniciado_en)).total_seconds()
        for j in jobs
        if j.iniciado_en is not None and j.finalizado_en is not None
    ]

    consultas = SaludConsultasResumen(
        total=len(jobs),
        exitosas=exitosas,
        fallidas=fallidas,
        tasa_exito=round(exitosas / len(jobs), 3) if jobs else None,
        duracion_prom_seg=(
            round(sum(duraciones_jobs) / len(duraciones_jobs), 2) if duraciones_jobs else None
        ),
    )

    return SaludResponse(periodo_horas=horas_atras, canario=canario, consultas=consultas)


@router.get("/errores-recientes", response_model=list[ErrorRecienteItem])
def obtener_errores_recientes(
    limite: int = 20,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Ultimos errores, mezclando canario y consultas normales pero
    etiquetados por tipo, ordenados por fecha -- pensado para el playbook
    de "SUNAT cambio algo, ¿que se revisa primero?": ver de un vistazo si
    el problema es solo del canario, solo de consultas de clientes, o
    ambos (lo que apunta mas fuerte a un cambio real en el portal).

    Filtrado por tenant_id en ambas queries (fix Fase R1): esta era la
    fuga mas seria del panel de salud -- devolvia empresa_ruc y
    empresa_razon_social de CUALQUIER tenant a cualquier usuario logueado.
    """
    items: list[ErrorRecienteItem] = []

    checks_fallidos = (
        db.query(CanarioCheck, Empresa)
        .join(Empresa, Empresa.id == CanarioCheck.empresa_id)
        .filter(CanarioCheck.exito.is_(False), Empresa.tenant_id == usuario.tenant_id)
        .order_by(CanarioCheck.ejecutado_en.desc())
        .limit(limite)
        .all()
    )
    for check, empresa in checks_fallidos:
        items.append(ErrorRecienteItem(
            tipo="canario",
            empresa_ruc=empresa.ruc,
            empresa_razon_social=empresa.razon_social,
            ocurrido_en=_con_utc(check.ejecutado_en),
            error=check.error,
        ))

    jobs_fallidos = (
        db.query(ConsultaJob, Empresa)
        .join(Empresa, Empresa.id == ConsultaJob.empresa_id)
        .filter(ConsultaJob.estado == "error", Empresa.tenant_id == usuario.tenant_id)
        .order_by(ConsultaJob.finalizado_en.desc())
        .limit(limite)
        .all()
    )
    for job, empresa in jobs_fallidos:
        items.append(ErrorRecienteItem(
            tipo="consulta",
            empresa_ruc=empresa.ruc,
            empresa_razon_social=empresa.razon_social,
            ocurrido_en=_con_utc(job.finalizado_en),
            error=job.error,
        ))

    items.sort(key=lambda i: i.ocurrido_en or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[:limite]


@router.get("/documentos-recientes", response_model=list[DocumentoRecienteItem])
def obtener_documentos_recientes(
    limite: int = 10,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Los ultimos N documentos (PDFs) que el scraper descargo, de CUALQUIER
    empresa del tenant -- pensado para una revision rapida de "esto
    funciona": confirmar de un vistazo que la descarga de documentos sigue
    trayendo archivos reales, sin tener que entrar empresa por empresa.
    Ordenado por descubierto_en (cuando el sistema lo encontro), no por la
    fecha de publicacion del mensaje -- asi refleja actividad reciente del
    scraper, no la antiguedad del tramite en si.
    """
    filas = (
        db.query(MensajeBuzon, Empresa)
        .join(Empresa, Empresa.id == MensajeBuzon.empresa_id)
        .filter(Empresa.tenant_id == usuario.tenant_id, MensajeBuzon.documento_ref.isnot(None))
        .order_by(MensajeBuzon.descubierto_en.desc())
        .limit(limite)
        .all()
    )
    return [
        DocumentoRecienteItem(
            mensaje_id=mensaje.id,
            empresa_id=empresa.id,
            empresa_ruc=empresa.ruc,
            empresa_razon_social=empresa.razon_social,
            asunto=mensaje.asunto,
            tipo=mensaje.tipo,
            fecha_publicacion=_con_utc(mensaje.fecha_publicacion),
            descubierto_en=_con_utc(mensaje.descubierto_en),
        )
        for mensaje, empresa in filas
    ]
