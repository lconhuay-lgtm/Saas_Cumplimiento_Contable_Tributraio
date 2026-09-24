"""
Control de acceso por rol DENTRO de un tenant (a pedido -- antes,
Usuario.rol existia en el modelo pero no restringia nada, cualquier
usuario del tenant veia todas sus empresas por igual).

Regla: "admin" ve todas las empresas del tenant (comportamiento de
siempre); "miembro" ve SOLO las que tiene asignadas
(Empresa.asignado_a_usuario_id == su propio id) -- y por extension, solo
los mensajes/tareas/jobs que cuelgan de esas empresas, porque todos esos
listados se filtran uniendo con Empresa y aplicando la misma condicion.

Centralizado aca porque el patron "buscar una empresa respetando quien
pregunta" estaba repetido suelto (con 4 variantes casi identicas) en
empresas.py, consultas.py, ficha_ruc.py y tareas.py.
"""
from fastapi import HTTPException, status
from sqlalchemy.orm import Query, Session

from app.models import Empresa, Usuario


def es_admin(usuario: Usuario) -> bool:
    return usuario.rol == "admin"


def filtrar_empresas_visibles(query: Query, usuario: Usuario) -> Query:
    """
    Aplica a cualquier query que ya tenga Empresa en el FROM/JOIN --
    siempre acota por tenant primero (aislamiento de siempre, sin cambios),
    y ademas por asignacion si quien pregunta no es admin.
    """
    query = query.filter(Empresa.tenant_id == usuario.tenant_id)
    if not es_admin(usuario):
        query = query.filter(Empresa.asignado_a_usuario_id == usuario.id)
    return query


def obtener_empresa_visible(empresa_id: str, usuario: Usuario, db: Session) -> Empresa:
    """
    Busca una empresa por id respetando la visibilidad de arriba. 404 (no
    403) tanto si no existe como si existe pero no es visible para este
    usuario -- no hay que confirmarle a un miembro que una empresa de otro
    companero existe.
    """
    empresa = filtrar_empresas_visibles(db.query(Empresa), usuario).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa no encontrada")
    return empresa
