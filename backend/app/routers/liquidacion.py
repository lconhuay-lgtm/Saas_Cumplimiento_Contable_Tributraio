"""
Liquidacion en vivo -- Etapa 1 (configuracion y acceso).

- Un admin activa o desactiva cada empresa (cuenta contra las incluidas en
  el plan, Tenant.liquidacion_incluidas; pasarse no se bloquea, se cobra aparte).
- El responsable asignado (Empresa.asignado_a_usuario_id) es el unico que
  guarda o borra las credenciales de la API del SIRE.
- "Probar conexion" pide el token a SUNAT y lista los periodos del SIRE.
- El regimen se sugiere por el codigo de tributo de sus pagos de Renta y el
  responsable (o un admin) lo confirma o lo cambia.
Cada cambio queda en LiquidacionEvento.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.acceso import es_admin, filtrar_empresas_visibles, obtener_empresa_visible
from app.database import get_db
from app.deps import get_usuario_actual
from app.models import (
    CredencialSol, DeclaracionSunat, Empresa, LiquidacionEmpresa, LiquidacionEvento, SireEstadoPeriodo, Tenant, Usuario,
)
from app.schemas import (
    REGIMENES_LIQUIDACION, LiquidacionActivarRequest, LiquidacionApiRequest, LiquidacionDetalleResponse,
    LiquidacionEmpresaItem, LiquidacionEventoItem, LiquidacionListaResponse, LiquidacionRegimenRequest,
)
from app.security import cifrar_clave_sol, descifrar_clave_sol
from app.sire_api import ErrorApiSire, probar_conexion

router = APIRouter(tags=["liquidacion"])

# Codigo de tributo de los pagos a cuenta de Renta (boleta 1662) -> regimen.
REGIMEN_POR_TRIBUTO = {"3031": "general", "3121": "mype", "3111": "especial"}


def _nombre(usuario: Usuario | None) -> str | None:
    if usuario is None:
        return None
    completo = " ".join(p for p in (usuario.nombre, usuario.apellidos) if p)
    return completo or usuario.email


def regimen_sugerido(db: Session, empresa_id: str) -> str | None:
    """El regimen del pago de Renta mas reciente, si hay alguno con codigo conocido."""
    fila = (
        db.query(DeclaracionSunat.cod_tributo)
        .filter(
            DeclaracionSunat.empresa_id == empresa_id,
            DeclaracionSunat.cod_tributo.in_(REGIMEN_POR_TRIBUTO.keys()),
        )
        .order_by(DeclaracionSunat.periodo.desc())
        .first()
    )
    return REGIMEN_POR_TRIBUTO[fila[0]] if fila else None


def _sire_periodos(db: Session, config: LiquidacionEmpresa | None, empresa_id: str) -> int | None:
    """Periodos del SIRE: los de la ultima prueba de la API, o los que ya leyo el modulo SIRE."""
    if config is not None and config.sire_periodos is not None:
        return config.sire_periodos
    n = db.query(SireEstadoPeriodo).filter(SireEstadoPeriodo.empresa_id == empresa_id).count()
    return n or None


def _estado(empresa: Empresa, config: LiquidacionEmpresa | None, periodos: int | None) -> str:
    if config is None or not config.activa:
        return "no_activada"
    if not empresa.asignado_a_usuario_id:
        return "falta_responsable"
    if config.api_estado == "sin_configurar":
        return "falta_api"
    if config.api_estado == "error":
        return "api_error"
    if config.api_estado == "sin_probar":
        return "sin_probar"
    if periodos == 0:
        return "no_afiliada"
    return "lista"


def _item(db: Session, empresa: Empresa, config: LiquidacionEmpresa | None) -> dict:
    periodos = _sire_periodos(db, config, empresa.id)
    return {
        "empresa_id": empresa.id,
        "ruc": empresa.ruc,
        "razon_social": empresa.razon_social,
        "responsable_id": empresa.asignado_a_usuario_id,
        "responsable_nombre": _nombre(empresa.asignado_a),
        "activa": bool(config and config.activa),
        "estado": _estado(empresa, config, periodos),
        "api_estado": config.api_estado if config else "sin_configurar",
        "api_mensaje": config.api_mensaje if config else None,
        "api_probado_en": config.api_probado_en if config else None,
        "regimen": config.regimen if config else None,
        "regimen_origen": config.regimen_origen if config else None,
        "regimen_sugerido": regimen_sugerido(db, empresa.id),
        "sire_periodos": periodos,
    }


def _config(db: Session, empresa_id: str) -> LiquidacionEmpresa:
    config = db.get(LiquidacionEmpresa, empresa_id)
    if config is None:
        config = LiquidacionEmpresa(empresa_id=empresa_id, activa=False, api_estado="sin_configurar")
        db.add(config)
    return config


def _evento(db: Session, empresa_id: str, usuario: Usuario | None, accion: str, detalle: str | None = None) -> None:
    db.add(LiquidacionEvento(empresa_id=empresa_id, usuario_id=usuario.id if usuario else None, accion=accion, detalle=detalle))


def _exigir_responsable(empresa: Empresa, usuario: Usuario) -> None:
    if not empresa.asignado_a_usuario_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta empresa no tiene responsable asignado. Asígnalo primero en la pestaña Configuración de la empresa.",
        )
    if empresa.asignado_a_usuario_id != usuario.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el responsable asignado de la empresa puede cambiar las credenciales de la API del SIRE.",
        )


@router.get("/liquidacion/empresas", response_model=LiquidacionListaResponse)
def listar_empresas_liquidacion(db: Session = Depends(get_db), usuario: Usuario = Depends(get_usuario_actual)):
    empresas = (
        filtrar_empresas_visibles(db.query(Empresa), usuario)
        .filter(Empresa.activo.is_(True))
        .order_by(Empresa.razon_social)
        .all()
    )
    configs = {
        c.empresa_id: c
        for c in db.query(LiquidacionEmpresa).filter(LiquidacionEmpresa.empresa_id.in_([e.id for e in empresas])).all()
    } if empresas else {}
    tenant = db.get(Tenant, usuario.tenant_id)
    activas_tenant = (
        db.query(LiquidacionEmpresa)
        .join(Empresa, Empresa.id == LiquidacionEmpresa.empresa_id)
        .filter(Empresa.tenant_id == usuario.tenant_id, Empresa.activo.is_(True), LiquidacionEmpresa.activa.is_(True))
        .count()
    )
    return {
        "incluidas": tenant.liquidacion_incluidas if tenant else 15,
        "activas": activas_tenant,
        "es_admin": es_admin(usuario),
        "empresas": [_item(db, e, configs.get(e.id)) for e in empresas],
    }


@router.post("/liquidacion/empresas/{empresa_id}/activar", response_model=LiquidacionEmpresaItem)
def activar_liquidacion(
    empresa_id: str,
    datos: LiquidacionActivarRequest,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    if not es_admin(usuario):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo un administrador puede activar o desactivar empresas.")
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    config = _config(db, empresa.id)
    if config.activa != datos.activa:
        config.activa = datos.activa
        if datos.activa:
            config.activada_en = datetime.now(timezone.utc)
            config.activada_por_usuario_id = usuario.id
            if not config.regimen:
                sugerido = regimen_sugerido(db, empresa.id)
                if sugerido:
                    config.regimen, config.regimen_origen = sugerido, "pagos"
        _evento(db, empresa.id, usuario, "activada" if datos.activa else "desactivada")
    db.commit()
    return _item(db, empresa, config)


@router.get("/empresas/{empresa_id}/liquidacion", response_model=LiquidacionDetalleResponse)
def detalle_liquidacion(empresa_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(get_usuario_actual)):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    config = db.get(LiquidacionEmpresa, empresa.id)
    eventos = (
        db.query(LiquidacionEvento, Usuario)
        .outerjoin(Usuario, Usuario.id == LiquidacionEvento.usuario_id)
        .filter(LiquidacionEvento.empresa_id == empresa.id)
        .order_by(LiquidacionEvento.creado_en.desc())
        .limit(20)
        .all()
    )
    client_id = config.api_client_id if config else None
    return {
        **_item(db, empresa, config),
        "api_client_id": f"••••{client_id[-4:]}" if client_id else None,
        "puede_editar_api": empresa.asignado_a_usuario_id == usuario.id,
        "es_admin": es_admin(usuario),
        "eventos": [
            LiquidacionEventoItem(accion=ev.accion, detalle=ev.detalle, usuario_nombre=_nombre(u), creado_en=ev.creado_en)
            for ev, u in eventos
        ],
    }


@router.put("/empresas/{empresa_id}/liquidacion/api", response_model=LiquidacionEmpresaItem)
def guardar_api_sire(
    empresa_id: str,
    datos: LiquidacionApiRequest,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    _exigir_responsable(empresa, usuario)
    config = _config(db, empresa.id)
    if not config.activa:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Primero un administrador debe activar la Liquidación en vivo para esta empresa.")
    config.api_client_id = datos.client_id.strip()
    config.api_secret_cifrado, config.api_dek_cifrada = cifrar_clave_sol(datos.client_secret.strip())
    config.api_estado, config.api_mensaje, config.api_probado_en, config.sire_periodos = "sin_probar", None, None, None
    _evento(db, empresa.id, usuario, "api_guardada")
    db.commit()
    return _item(db, empresa, config)


@router.delete("/empresas/{empresa_id}/liquidacion/api", response_model=LiquidacionEmpresaItem)
def borrar_api_sire(empresa_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(get_usuario_actual)):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    _exigir_responsable(empresa, usuario)
    config = _config(db, empresa.id)
    config.api_client_id = config.api_secret_cifrado = config.api_dek_cifrada = None
    config.api_estado, config.api_mensaje, config.api_probado_en, config.sire_periodos = "sin_configurar", None, None, None
    _evento(db, empresa.id, usuario, "api_borrada")
    db.commit()
    return _item(db, empresa, config)


@router.post("/empresas/{empresa_id}/liquidacion/probar", response_model=LiquidacionEmpresaItem)
def probar_api_sire(empresa_id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(get_usuario_actual)):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    if not (es_admin(usuario) or empresa.asignado_a_usuario_id == usuario.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el responsable asignado o un administrador puede probar la conexión.")
    config = db.get(LiquidacionEmpresa, empresa.id)
    if config is None or not config.api_client_id or not config.api_secret_cifrado:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Primero guarda las credenciales de la API del SIRE.")
    credencial = db.query(CredencialSol).filter(CredencialSol.empresa_id == empresa.id).first()
    if credencial is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La empresa no tiene clave SOL guardada.")

    try:
        periodos = probar_conexion(
            config.api_client_id,
            descifrar_clave_sol(config.api_secret_cifrado, config.api_dek_cifrada),
            empresa.ruc,
            credencial.usuario_sol,
            descifrar_clave_sol(credencial.clave_cifrada, credencial.dek_cifrada),
        )
        config.api_estado, config.sire_periodos = "ok", periodos
        config.api_mensaje = (
            f"Conectado. El SIRE lista {periodos} periodo(s)." if periodos
            else "Conectado, pero el SIRE no lista periodos: la empresa no está afiliada al SIRE."
        )
    except ErrorApiSire as e:
        config.api_estado, config.api_mensaje = "error", str(e)
    config.api_probado_en = datetime.now(timezone.utc)
    _evento(db, empresa.id, usuario, "conexion_probada", config.api_mensaje)
    db.commit()
    return _item(db, empresa, config)


@router.put("/empresas/{empresa_id}/liquidacion/regimen", response_model=LiquidacionEmpresaItem)
def cambiar_regimen(
    empresa_id: str,
    datos: LiquidacionRegimenRequest,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    if not (es_admin(usuario) or empresa.asignado_a_usuario_id == usuario.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el responsable asignado o un administrador puede cambiar el régimen.")
    if datos.regimen not in REGIMENES_LIQUIDACION:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Régimen no válido.")
    config = _config(db, empresa.id)
    config.regimen, config.regimen_origen = datos.regimen, "manual"
    _evento(db, empresa.id, usuario, "regimen_cambiado", datos.regimen)
    db.commit()
    return _item(db, empresa, config)
