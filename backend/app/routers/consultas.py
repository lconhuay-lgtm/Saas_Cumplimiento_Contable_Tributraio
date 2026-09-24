"""Encolar consultas al buzon y consultar su estado/resultado."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Empresa, ConsultaJob, CredencialSol, MensajeBuzon, Usuario
from app.schemas import JobResponse, MensajeBuzonResponse, MensajeUpdate, MarcarLeidosResponse, EstadoConsultasResponse
from app.deps import get_usuario_actual
from app.queue_conn import cola_consultas
from app.jobs import ejecutar_consulta_buzon
from app.rate_limit import verificar_limite_ruc, LimiteExcedido
from app.almacenamiento import leer_documento, AlmacenamientoError

router = APIRouter(tags=["consultas"])

ESPACIADO_CONSULTAR_TODAS_SEG = 45

# Ventana de tiempo para decidir que jobs pertenecen a "la tanda actual" al
# calcular el progreso de una consulta masiva (ver /consultas/estado).
# No existe un concepto de "lote" en la base de datos -- se aproxima con
# esta ventana, generosa a proposito: con ESPACIADO_CONSULTAR_TODAS_SEG=45s
# y cada consulta individual pudiendo tardar 1-2 minutos, una tanda de
# varias decenas de empresas puede tardar mas de una hora en drenar del
# todo.
VENTANA_ESTADO_CONSULTAS_MIN = 90


def _get_empresa_del_tenant(empresa_id: str, usuario: Usuario, db: Session) -> Empresa:
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.tenant_id == usuario.tenant_id)
        .first()
    )
    if not empresa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa no encontrada")
    return empresa


@router.post("/empresas/{empresa_id}/consultar", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def consultar_empresa(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = _get_empresa_del_tenant(empresa_id, usuario, db)

    try:
        verificar_limite_ruc(empresa.ruc)
    except LimiteExcedido as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    job = ConsultaJob(empresa_id=empresa.id, solicitado_por=usuario.id, estado="pendiente")
    db.add(job)
    db.commit()
    db.refresh(job)

    cola_consultas.enqueue(ejecutar_consulta_buzon, job.id, job_timeout="10m")

    return job


@router.post("/empresas/consultar-todas")
def consultar_todas_empresas(
    espaciado_seg: int = ESPACIADO_CONSULTAR_TODAS_SEG,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresas = (
        db.query(Empresa)
        .filter(Empresa.tenant_id == usuario.tenant_id, Empresa.activo.is_(True))
        .all()
    )

    encoladas = 0
    saltadas_sin_credencial = 0
    for empresa in empresas:
        tiene_credencial = db.query(CredencialSol.id).filter(CredencialSol.empresa_id == empresa.id).first()
        if not tiene_credencial:
            saltadas_sin_credencial += 1
            continue

        job = ConsultaJob(empresa_id=empresa.id, solicitado_por=usuario.id, estado="pendiente")
        db.add(job)
        db.commit()
        db.refresh(job)

        cola_consultas.enqueue_in(
            timedelta(seconds=encoladas * espaciado_seg),
            ejecutar_consulta_buzon,
            job.id,
            job_timeout="10m",
        )
        encoladas += 1

    return {
        "empresas_encoladas": encoladas,
        "saltadas_sin_credencial": saltadas_sin_credencial,
        "espaciado_seg": espaciado_seg,
    }


@router.get("/consultas/estado", response_model=EstadoConsultasResponse)
def estado_consultas(
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Progreso de la "tanda" de consultas mas reciente de este tenant --
    dispare quien la haya disparado: el boton "Consultar todas", el
    chequeo automatico programado, o una consulta individual. El frontend
    hace polling de este endpoint para mostrar el avance y deshabilitar el
    boton "Consultar todas" mientras haya algo en curso, sin importar quien
    lo haya iniciado.

    No hay un concepto de "lote" en la base de datos, asi que se aproxima
    mirando los ConsultaJob creados en los ultimos VENTANA_ESTADO_CONSULTAS_MIN
    minutos para las empresas de este tenant.
    """
    desde = datetime.now(timezone.utc) - timedelta(minutes=VENTANA_ESTADO_CONSULTAS_MIN)
    jobs_recientes = (
        db.query(ConsultaJob)
        .join(Empresa, Empresa.id == ConsultaJob.empresa_id)
        .filter(Empresa.tenant_id == usuario.tenant_id, ConsultaJob.creado_en >= desde)
        .all()
    )

    if not jobs_recientes:
        return EstadoConsultasResponse(en_curso=False)

    completados = sum(1 for j in jobs_recientes if j.estado == "completado")
    en_progreso = sum(1 for j in jobs_recientes if j.estado == "en_progreso")
    pendientes = sum(1 for j in jobs_recientes if j.estado == "pendiente")
    con_error = sum(1 for j in jobs_recientes if j.estado == "error")

    return EstadoConsultasResponse(
        en_curso=(pendientes + en_progreso) > 0,
        total=len(jobs_recientes),
        completados=completados,
        en_progreso=en_progreso,
        pendientes=pendientes,
        con_error=con_error,
        iniciado_en=min(j.creado_en for j in jobs_recientes),
    )


@router.get("/empresas/{empresa_id}/jobs", response_model=list[JobResponse])
def listar_jobs(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = _get_empresa_del_tenant(empresa_id, usuario, db)
    return (
        db.query(ConsultaJob)
        .filter(ConsultaJob.empresa_id == empresa.id)
        .order_by(ConsultaJob.creado_en.desc())
        .limit(20)
        .all()
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
def obtener_job(
    job_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    job = (
        db.query(ConsultaJob)
        .join(Empresa, Empresa.id == ConsultaJob.empresa_id)
        .filter(ConsultaJob.id == job_id, Empresa.tenant_id == usuario.tenant_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job no encontrado")
    return job


@router.get("/empresas/{empresa_id}/mensajes", response_model=list[MensajeBuzonResponse])
def listar_mensajes(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = _get_empresa_del_tenant(empresa_id, usuario, db)
    mensajes = (
        db.query(MensajeBuzon)
        .filter(MensajeBuzon.empresa_id == empresa.id)
        .order_by(MensajeBuzon.fecha_publicacion.desc())
        .all()
    )
    return [_a_respuesta_mensaje(m) for m in mensajes]


def _a_respuesta_mensaje(mensaje: MensajeBuzon) -> MensajeBuzonResponse:
    r = MensajeBuzonResponse.model_validate(mensaje)
    r.tiene_documento = mensaje.documento_ref is not None
    return r


@router.patch("/empresas/{empresa_id}/mensajes/{mensaje_id}", response_model=MensajeBuzonResponse)
def actualizar_mensaje(
    empresa_id: str,
    mensaje_id: str,
    data: MensajeUpdate,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = _get_empresa_del_tenant(empresa_id, usuario, db)
    mensaje = (
        db.query(MensajeBuzon)
        .filter(MensajeBuzon.id == mensaje_id, MensajeBuzon.empresa_id == empresa.id)
        .first()
    )
    if not mensaje:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mensaje no encontrado")
    mensaje.leido = data.leido
    db.commit()
    db.refresh(mensaje)
    return _a_respuesta_mensaje(mensaje)


@router.get("/empresas/{empresa_id}/mensajes/{mensaje_id}/documento")
def obtener_documento(
    empresa_id: str,
    mensaje_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = _get_empresa_del_tenant(empresa_id, usuario, db)
    mensaje = (
        db.query(MensajeBuzon)
        .filter(MensajeBuzon.id == mensaje_id, MensajeBuzon.empresa_id == empresa.id)
        .first()
    )
    if not mensaje or not mensaje.documento_ref:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay documento disponible para este mensaje")

    try:
        contenido = leer_documento(mensaje.documento_ref)
    except AlmacenamientoError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return Response(content=contenido, media_type="application/pdf")


@router.post("/empresas/{empresa_id}/mensajes/marcar-leidos", response_model=MarcarLeidosResponse)
def marcar_todos_leidos(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = _get_empresa_del_tenant(empresa_id, usuario, db)
    actualizados = (
        db.query(MensajeBuzon)
        .filter(MensajeBuzon.empresa_id == empresa.id, MensajeBuzon.leido.is_(False))
        .update({MensajeBuzon.leido: True}, synchronize_session=False)
    )
    db.commit()
    return MarcarLeidosResponse(actualizados=actualizados)


@router.post("/empresas/marcar-todos-leidos", response_model=MarcarLeidosResponse)
def marcar_todos_leidos_global(
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Version global del endpoint de arriba -- marca como leidos TODOS los
    mensajes pendientes de TODAS las empresas del tenant de una sola vez
    (util para "limpiar" el estado inicial de una cuenta recien conectada,
    por ejemplo la primera vez que se importan muchas empresas y ya se
    revisaron sus mensajes por otro medio).

    Se filtra por Empresa.id.in_(...) en vez de un JOIN dentro del propio
    UPDATE -- mismo patron que _con_estadisticas() en routers/empresas.py
    -- porque un UPDATE masivo de SQLAlchemy con join no es portable entre
    motores de base de datos.
    """
    ids_empresas_del_tenant = [
        e.id for e in db.query(Empresa.id).filter(Empresa.tenant_id == usuario.tenant_id).all()
    ]
    if not ids_empresas_del_tenant:
        return MarcarLeidosResponse(actualizados=0)

    actualizados = (
        db.query(MensajeBuzon)
        .filter(MensajeBuzon.empresa_id.in_(ids_empresas_del_tenant), MensajeBuzon.leido.is_(False))
        .update({MensajeBuzon.leido: True}, synchronize_session=False)
    )
    db.commit()
    return MarcarLeidosResponse(actualizados=actualizados)
