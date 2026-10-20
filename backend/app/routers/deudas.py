"""
Deudas: valores pendientes de pago de cada empresa (Revision de mis deudas >
Consulta valores pendientes de pago, desde 2020 hasta el mes pasado), con su
historial -- incluye los que ya no aparecen en SUNAT. Alimenta la pestana
"Deudas" del modulo Cumplimiento; se relee sola cada dia (ver
scheduler_entry.job_deudas_diario).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ConsultaDeudasJob, EmbargoNotificado, Empresa, RecCoactiva, Usuario, ValorDeuda
from app.cumplimiento import ESTADOS_EN_CURSO, encolar_lecturas, filtrar_activas_en_sunat
from app.schemas import (
    ConsultaDeudasJobResponse, CumplimientoDeudasFila, CumplimientoDeudasResponse, EmbargoItem, MarcarValoresVistosRequest,
    MarcarVistasResponse, RecItem, ValorDeudaItem, ValoresNuevosGrupo, ValorNuevoItem,
)
from app.deps import get_usuario_actual
from app.queue_conn import cola_consultas
from app.jobs import ejecutar_consulta_deudas
from app.rate_limit import verificar_limite_ruc, LimiteExcedido
from app.acceso import filtrar_empresas_visibles, obtener_empresa_visible

router = APIRouter(tags=["deudas"])


def _empresas_cumplimiento(db: Session, usuario: Usuario):
    return (
        filtrar_activas_en_sunat(filtrar_empresas_visibles(db.query(Empresa), usuario))
        .filter(Empresa.activo.is_(True))
        .order_by(Empresa.razon_social)
        .all()
    )


@router.post("/empresas/{empresa_id}/deudas/consultar", response_model=ConsultaDeudasJobResponse, status_code=status.HTTP_202_ACCEPTED)
def consultar_deudas(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    en_curso = (
        db.query(ConsultaDeudasJob)
        .filter(ConsultaDeudasJob.empresa_id == empresa.id, ConsultaDeudasJob.estado.in_(ESTADOS_EN_CURSO))
        .first()
    )
    if en_curso:
        return en_curso

    try:
        verificar_limite_ruc(empresa.ruc)
    except LimiteExcedido as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    job = ConsultaDeudasJob(empresa_id=empresa.id, solicitado_por=usuario.id, estado="pendiente")
    db.add(job)
    db.commit()
    db.refresh(job)
    cola_consultas.enqueue(ejecutar_consulta_deudas, job.id, job_timeout="10m", at_front=True)
    return job


@router.get("/cumplimiento/deudas", response_model=CumplimientoDeudasResponse)
def cumplimiento_deudas(
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """Cuadro de deudas: todos los valores (vigentes y los que ya no aparecen) de cada empresa visible."""
    empresas = _empresas_cumplimiento(db, usuario)
    ids = [e.id for e in empresas]
    if not ids:
        return CumplimientoDeudasResponse(filas=[])

    valores_por_empresa: dict[str, list[ValorDeuda]] = {}
    for v in (
        db.query(ValorDeuda)
        .filter(ValorDeuda.empresa_id.in_(ids))
        .order_by(ValorDeuda.vigente.desc(), ValorDeuda.periodo.desc(), ValorDeuda.num_valor)
    ):
        valores_por_empresa.setdefault(v.empresa_id, []).append(v)
    embargos_por_empresa: dict[str, list[EmbargoNotificado]] = {}
    for e in (
        db.query(EmbargoNotificado)
        .filter(EmbargoNotificado.empresa_id.in_(ids))
        .order_by(EmbargoNotificado.fecha_registro.desc())
    ):
        embargos_por_empresa.setdefault(e.empresa_id, []).append(e)
    recs_por_empresa: dict[str, list[RecCoactiva]] = {}
    for r in db.query(RecCoactiva).filter(RecCoactiva.empresa_id.in_(ids)).order_by(RecCoactiva.fecha_emision.desc()):
        recs_por_empresa.setdefault(r.empresa_id, []).append(r)

    en_curso = {
        eid for (eid,) in db.query(ConsultaDeudasJob.empresa_id)
        .filter(ConsultaDeudasJob.empresa_id.in_(ids), ConsultaDeudasJob.estado.in_(ESTADOS_EN_CURSO))
    }
    ultimo_job: dict[str, ConsultaDeudasJob] = {}
    ultima_lectura_ok = {}
    for job in (
        db.query(ConsultaDeudasJob)
        .filter(ConsultaDeudasJob.empresa_id.in_(ids), ConsultaDeudasJob.estado.in_(("completado", "error")))
        .order_by(ConsultaDeudasJob.creado_en)
    ):
        ultimo_job[job.empresa_id] = job
        if job.estado == "completado":
            ultima_lectura_ok[job.empresa_id] = job.finalizado_en

    filas = []
    for e in empresas:
        job = ultimo_job.get(e.id)
        estado_rec = {r.num_rec: r.estado for r in recs_por_empresa.get(e.id, [])}
        valores = []
        for v in valores_por_empresa.get(e.id, []):
            item = ValorDeudaItem.model_validate(v)
            item.rec_estado = estado_rec.get(v.num_expediente_coactivo or "")
            valores.append(item)
        filas.append(CumplimientoDeudasFila(
            empresa_id=e.id,
            ruc=e.ruc,
            razon_social=e.razon_social,
            valores=valores,
            embargos=[EmbargoItem.model_validate(x) for x in embargos_por_empresa.get(e.id, [])],
            recs=[RecItem.model_validate(x) for x in recs_por_empresa.get(e.id, [])],
            actualizado_en=ultima_lectura_ok.get(e.id),
            consulta_en_curso=e.id in en_curso,
            ultimo_error=job.error if job is not None and job.estado == "error" else None,
        ))
    return CumplimientoDeudasResponse(filas=filas)


@router.get("/deudas/valores-nuevos", response_model=list[ValoresNuevosGrupo])
def listar_valores_nuevos(
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Ventana emergente al entrar a la app (ModalValoresNuevos.js): valores que
    aparecieron (o volvieron a aparecer) en SUNAT y nadie vio todavia --
    mismo patron que /notificaciones/nuevas para el buzon.
    """
    filas = (
        filtrar_activas_en_sunat(
            filtrar_empresas_visibles(
                db.query(ValorDeuda, Empresa).join(Empresa, Empresa.id == ValorDeuda.empresa_id), usuario
            )
        )
        .filter(Empresa.activo.is_(True), ValorDeuda.notificado_popup.is_(False), ValorDeuda.vigente.is_(True))
        .order_by(Empresa.razon_social.asc(), ValorDeuda.saldo_total.desc())
        .all()
    )
    grupos: dict[str, ValoresNuevosGrupo] = {}
    for valor, empresa in filas:
        grupo = grupos.setdefault(
            empresa.id,
            ValoresNuevosGrupo(empresa_id=empresa.id, ruc=empresa.ruc, razon_social=empresa.razon_social, valores=[]),
        )
        item = ValorNuevoItem.model_validate(valor)
        ultimo_alta = next(
            (h.get("evento") for h in reversed(valor.historial or []) if h.get("evento") in ("nuevo", "reaparecio")),
            None,
        )
        item.reaparecio = ultimo_alta == "reaparecio"
        grupo.valores.append(item)
    return list(grupos.values())


@router.post("/deudas/valores-nuevos/marcar-vistos", response_model=MarcarVistasResponse)
def marcar_valores_vistos(
    data: MarcarValoresVistosRequest,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    # Acotado a empresas visibles -- nadie marca como vistos valores ajenos mandando ids a mano.
    ids_empresas_visibles = [e.id for e in filtrar_empresas_visibles(db.query(Empresa.id), usuario).all()]
    if not ids_empresas_visibles:
        return MarcarVistasResponse(actualizados=0)
    actualizados = (
        db.query(ValorDeuda)
        .filter(ValorDeuda.id.in_(data.valor_ids), ValorDeuda.empresa_id.in_(ids_empresas_visibles))
        .update({ValorDeuda.notificado_popup: True}, synchronize_session=False)
    )
    db.commit()
    return MarcarVistasResponse(actualizados=actualizados)


@router.post("/cumplimiento/deudas/consultar-todas")
def consultar_deudas_todas(
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """Encola la lectura de valores pendientes de todas las empresas visibles, espaciadas como la consulta masiva."""
    return encolar_lecturas(
        db, _empresas_cumplimiento(db, usuario), ConsultaDeudasJob, ejecutar_consulta_deudas, solicitado_por=usuario.id
    )
