"""
Ventana emergente de "mensajes nuevos" que se muestra al entrar a la app
(ver ModalNotificacionesNuevas.js en el frontend) -- distinto del correo
inmediato (jobs.py) y del resumen diario (scheduler_job.py), aunque los
tres se disparan por el mismo hecho (una consulta posterior al alta
inicial de una empresa encontro mensajes nuevos, ver
ConsultaJob.es_alta_inicial).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Empresa, MensajeBuzon, Usuario
from app.schemas import (
    NotificacionEmpresaGrupo,
    MensajeNotificacionItem,
    MarcarVistasRequest,
    MarcarVistasResponse,
)
from app.deps import get_usuario_actual
from app.acceso import filtrar_empresas_visibles

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


@router.get("/nuevas", response_model=list[NotificacionEmpresaGrupo])
def listar_notificaciones_nuevas(
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    filas = (
        filtrar_empresas_visibles(
            db.query(MensajeBuzon, Empresa).join(Empresa, Empresa.id == MensajeBuzon.empresa_id),
            usuario,
        )
        .filter(MensajeBuzon.notificado_popup.is_(False))
        .order_by(Empresa.razon_social.asc(), MensajeBuzon.fecha_publicacion.desc())
        .all()
    )

    grupos: dict[str, NotificacionEmpresaGrupo] = {}
    for mensaje, empresa in filas:
        grupo = grupos.get(empresa.id)
        if grupo is None:
            grupo = NotificacionEmpresaGrupo(
                empresa_id=empresa.id, ruc=empresa.ruc, razon_social=empresa.razon_social, mensajes=[]
            )
            grupos[empresa.id] = grupo
        grupo.mensajes.append(
            MensajeNotificacionItem(id=mensaje.id, asunto=mensaje.asunto, fecha_publicacion=mensaje.fecha_publicacion)
        )

    return list(grupos.values())


@router.post("/marcar-vistas", response_model=MarcarVistasResponse)
def marcar_notificaciones_vistas(
    data: MarcarVistasRequest,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    # Acotado a empresas visibles para este usuario -- evita que alguien
    # marque como vistos mensajes de una empresa ajena mandando ids a mano.
    ids_empresas_visibles = [e.id for e in filtrar_empresas_visibles(db.query(Empresa.id), usuario).all()]
    if not ids_empresas_visibles:
        return MarcarVistasResponse(actualizados=0)

    actualizados = (
        db.query(MensajeBuzon)
        .filter(MensajeBuzon.id.in_(data.mensaje_ids), MensajeBuzon.empresa_id.in_(ids_empresas_visibles))
        .update({MensajeBuzon.notificado_popup: True}, synchronize_session=False)
    )
    db.commit()
    return MarcarVistasResponse(actualizados=actualizados)
