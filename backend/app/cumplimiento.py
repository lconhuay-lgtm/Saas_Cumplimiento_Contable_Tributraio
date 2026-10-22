"""
Piezas compartidas del modulo Cumplimiento (SIRE y Deudas): que empresas
entran al cuadro y como se encolan sus lecturas a SUNAT -- las usan tanto
los botones "Consultar todas" (routers/sire.py, routers/deudas.py) como las
lecturas programadas (scheduler_job.py).
"""
from datetime import timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Query, Session

from app.models import CredencialSol, Empresa, Tenant
from app.queue_conn import cola_consultas
from app.rate_limit import espaciado_consultas_seg

ESTADOS_EN_CURSO = ("pendiente", "en_progreso")


def filtrar_activas_en_sunat(query: Query) -> Query:
    """
    A pedido: las empresas suspendidas, de baja de oficio, baja definitiva o
    cualquier estado que no sea ACTIVO no aparecen en Cumplimiento (ni se
    consultan para el). Sin estado leido todavia (None) se muestran -- es
    una empresa recien cargada, no una dada de baja.
    """
    return query.filter(
        or_(
            Empresa.estado_contribuyente.is_(None),
            func.upper(func.trim(Empresa.estado_contribuyente)) == "ACTIVO",
        )
    )


def empresas_de_tenants_activos(db: Session) -> Query:
    """Empresas activas de todos los tenants activos, para las lecturas programadas (sin usuario que pregunte)."""
    return (
        db.query(Empresa)
        .join(Tenant, Tenant.id == Empresa.tenant_id)
        .filter(Empresa.activo.is_(True), Tenant.activo.is_(True))
    )


def encolar_lecturas(
    db: Session, empresas, modelo_job, funcion_job, solicitado_por: str | None = None, datos_job: dict | None = None,
) -> dict:
    """
    Crea un job 'pendiente' de `modelo_job` por empresa y lo programa en la
    cola espaciado igual que la consulta masiva del buzon. Salta las que no
    tienen credenciales SOL o ya tienen una lectura de este tipo en curso.
    `datos_job`: campos extra del job (p. ej. los criterios de Detracciones).
    """
    espaciado_seg = espaciado_consultas_seg()
    encoladas = 0
    saltadas = 0
    for empresa in empresas:
        tiene_credencial = db.query(CredencialSol.id).filter(CredencialSol.empresa_id == empresa.id).first()
        ya_en_curso = (
            db.query(modelo_job.id)
            .filter(modelo_job.empresa_id == empresa.id, modelo_job.estado.in_(ESTADOS_EN_CURSO))
            .first()
        )
        if not tiene_credencial or ya_en_curso:
            saltadas += 1
            continue
        job = modelo_job(empresa_id=empresa.id, solicitado_por=solicitado_por, estado="pendiente", **(datos_job or {}))
        db.add(job)
        db.commit()
        cola_consultas.enqueue_in(
            timedelta(seconds=encoladas * espaciado_seg),
            funcion_job,
            job.id,
            job_timeout="10m",
        )
        encoladas += 1
    return {"empresas_encoladas": encoladas, "saltadas": saltadas, "espaciado_seg": espaciado_seg}
