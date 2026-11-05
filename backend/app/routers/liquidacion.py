"""
Liquidacion en vivo -- Etapa 1 (configuracion y acceso).

- Un admin activa o desactiva cada empresa (cuenta contra las incluidas en
  el plan, Tenant.liquidacion_incluidas; pasarse no se bloquea, se cobra aparte).
- El responsable asignado (Empresa.asignado_a_usuario_id) es el unico que
  guarda o borra las credenciales de la API del SIRE.
- "Probar conexion" pide el token a SUNAT y lista los periodos del SIRE.
- El regimen se sugiere por el codigo de tributo de sus pagos de Renta y el
  responsable (o un admin) lo confirma o lo cambia.
- Bloque 1 del piloto: el responsable (o un admin) pide leer de SUNAT los
  datos de un periodo (ver jobs_liquidacion.py) y ve el avance y lo guardado.
- Bloque 2: el estimado del IGV y la Renta del periodo (calculo_liquidacion.py)
  en el tablero de la empresa y en el panel de las empresas activadas.
- Fase 4: estado del mes, "Requiere atencion", la marca "Revisado" (un
  LiquidacionEvento "revisado" con el periodo) y "Actualizar todas" del panel.
Cada cambio queda en LiquidacionEvento.
"""
import math
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.acceso import es_admin, filtrar_empresas_visibles, obtener_empresa_visible
from app.calculo_liquidacion import ACCION_VENTAS_ESCRITAS, calcular_periodo, serie_diaria
from app.credito_compras import MESES_ATRAS, MOTIVOS as MOTIVOS_COMPRA, RevisionCompras
from app.database import get_db
from app.deps import get_usuario_actual
from app.hora_peru import hoy_peru
from app.jobs_liquidacion import (
    ESPACIADO_AUTOMATICO_SEG, FUENTES, crear_lecturas, encolar_lecturas, lecturas_en_curso, rango_fuente, sumar_meses,
)
from app.models import (
    CredencialSol, DeclaracionSunat, Empresa, LiquidacionComprobante, LiquidacionCompraDecision, LiquidacionCuentaControl,
    LiquidacionDeclaracion, LiquidacionEmpresa, LiquidacionEvento, LiquidacionLectura, LiquidacionReglaProveedor,
    LiquidacionRetencionPercepcion, SireEstadoPeriodo, Tenant, Usuario,
)
from app.schemas import (
    REGIMENES_LIQUIDACION, LiquidacionActivarRequest, LiquidacionApiRequest, LiquidacionDetalleResponse,
    LiquidacionCalculoResponse, LiquidacionEmpresaItem, LiquidacionEventoItem, LiquidacionLecturaRequest,
    LiquidacionLecturasResponse, LiquidacionListaResponse, LiquidacionPanelResponse, LiquidacionRegimenRequest,
    LiquidacionSerieResponse, LiquidacionActualizarResponse, LiquidacionPeriodoRequest, LiquidacionRevisadoItem,
    LiquidacionVentasRequest, LiquidacionComprasResponse, LiquidacionCompraDecisionRequest,
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
    config = db.get(LiquidacionEmpresa, empresa.id)
    if config is None or not config.activa:
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
    config = db.get(LiquidacionEmpresa, empresa.id)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Esta empresa no tiene credenciales guardadas.")
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


# --- Bloque 1: lecturas de SUNAT ---

def _puede_leer(empresa: Empresa, usuario: Usuario) -> bool:
    return es_admin(usuario) or empresa.asignado_a_usuario_id == usuario.id


def _resumen_periodo(db: Session, empresa_id: str, periodo: str, hasta_cuenta: str) -> dict:
    """Lo que hay guardado para el periodo, para que se pueda revisar contra SUNAT."""
    C = LiquidacionComprobante
    resumen = {}
    for libro, nombre in (("RVIE", "ventas"), ("RCE", "compras")):
        n, base, igv = db.query(
            func.count(C.id), func.coalesce(func.sum(C.base_gravada + C.descuento_base), 0),
            func.coalesce(func.sum(C.igv + C.descuento_igv), 0),
        ).filter(C.empresa_id == empresa_id, C.libro == libro, C.fuente == "propuesta", C.periodo == periodo).one()
        resumen[nombre] = {"cantidad": n, "base": round(base, 2), "igv": round(igv, 2)}

    R = LiquidacionRetencionPercepcion
    for tipo, origen, nombre in (("retencion", "comprobante", "retenciones"), ("percepcion", "comprobante", "percepciones"),
                                 ("percepcion", "aduanas", "aduanas")):
        n, monto = db.query(func.count(R.id), func.coalesce(func.sum(R.monto), 0)).filter(
            R.empresa_id == empresa_id, R.tipo == tipo, R.origen == origen, R.periodo == periodo, R.cuenta.is_(True),
        ).one()
        resumen[nombre] = {"cantidad": n, "monto": round(monto, 2)}

    D = LiquidacionDeclaracion
    n, ultimo = db.query(func.count(D.id), func.max(D.periodo)).filter(D.empresa_id == empresa_id, D.vigente.is_(True)).one()
    resumen["declaraciones"] = {"cantidad": n, "ultimo_periodo": ultimo}

    CC = LiquidacionCuentaControl
    n, ultimo = db.query(func.count(func.distinct(CC.periodo)), func.max(CC.periodo)).filter(
        CC.empresa_id == empresa_id, CC.periodo <= hasta_cuenta,
    ).one()
    resumen["cuenta_control"] = {"periodos": n, "ultimo_periodo": ultimo}
    return resumen


def _estado_lecturas(db: Session, empresa: Empresa, usuario: Usuario, periodo: str) -> dict:
    hoy = hoy_peru()
    ultimas = []
    for fuente in FUENTES:
        lectura = (
            db.query(LiquidacionLectura)
            .filter(
                LiquidacionLectura.empresa_id == empresa.id,
                LiquidacionLectura.fuente == fuente,
                LiquidacionLectura.periodo_hasta == rango_fuente(fuente, periodo, hoy)[1],
            )
            .order_by(LiquidacionLectura.creado_en.desc())
            .first()
        )
        if lectura is not None:
            ultimas.append(lectura)
    return {
        "periodo": periodo,
        "en_curso": bool(lecturas_en_curso(db, empresa.id, datetime.now(timezone.utc))),
        "puede_leer": _puede_leer(empresa, usuario),
        "lecturas": ultimas,
        "resumen": _resumen_periodo(db, empresa.id, periodo, rango_fuente("cuenta_control", periodo, hoy)[1]),
    }


@router.get("/empresas/{empresa_id}/liquidacion/lecturas", response_model=LiquidacionLecturasResponse)
def ver_lecturas(
    empresa_id: str,
    periodo: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    return _estado_lecturas(db, empresa, usuario, periodo)


@router.post("/empresas/{empresa_id}/liquidacion/lecturas", response_model=LiquidacionLecturasResponse)
def pedir_lecturas(
    empresa_id: str,
    datos: LiquidacionLecturaRequest,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    if not _puede_leer(empresa, usuario):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el responsable asignado o un administrador puede leer los datos de SUNAT.")
    config = db.get(LiquidacionEmpresa, empresa.id)
    if config is None or not config.activa:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Primero un administrador debe activar la Liquidación en vivo para esta empresa.")
    if datos.periodo > hoy_peru().strftime("%Y-%m"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ese periodo todavía no empieza.")
    if db.query(CredencialSol).filter(CredencialSol.empresa_id == empresa.id).first() is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La empresa no tiene clave SOL guardada.")

    tiene_api = bool(config.api_client_id and config.api_secret_cifrado)
    fuentes = datos.fuentes or [f for f in FUENTES if f != "sire" or tiene_api]
    if any(f not in FUENTES for f in fuentes):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fuente no válida.")
    if "sire" in fuentes and not tiene_api:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Primero guarda las credenciales de la API del SIRE.")
    if lecturas_en_curso(db, empresa.id, datetime.now(timezone.utc)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya hay una lectura en curso para esta empresa. Espera a que termine.")

    lecturas = crear_lecturas(db, empresa.id, usuario.id, datos.periodo, fuentes)
    _evento(db, empresa.id, usuario, "lectura_solicitada", datos.periodo)
    db.commit()
    encolar_lecturas(lecturas)
    return _estado_lecturas(db, empresa, usuario, datos.periodo)


# --- Bloque 2: calculo del IGV y la Renta ---

PATRON_PERIODO = r"^\d{4}-(0[1-9]|1[0-2])$"

# "Requiere atencion" (4.6) por la configuracion: sin API del SIRE no hay estimado al dia.
MOTIVOS_CONFIG = {
    "falta_responsable": "Falta asignar un responsable",
    "falta_api": "Falta configurar la API del SIRE",
    "sin_probar": "Falta probar la API del SIRE",
    "api_error": "La API del SIRE dio error en la última prueba",
    "no_afiliada": "No afiliada al SIRE",
}


def _revisiones(db: Session, empresa_ids: list[str], periodo: str) -> dict[str, dict]:
    """La ultima marca "Revisado" (4.9) del periodo de cada empresa."""
    filas = (
        db.query(LiquidacionEvento, Usuario)
        .outerjoin(Usuario, Usuario.id == LiquidacionEvento.usuario_id)
        .filter(
            LiquidacionEvento.empresa_id.in_(empresa_ids or [""]),
            LiquidacionEvento.accion == "revisado",
            LiquidacionEvento.detalle == periodo,
        )
        .order_by(LiquidacionEvento.creado_en)
        .all()
    )
    return {ev.empresa_id: {"usuario_nombre": _nombre(u), "fecha": ev.creado_en} for ev, u in filas}


def _estado_config(db: Session, empresa: Empresa) -> str:
    config = db.get(LiquidacionEmpresa, empresa.id)
    return _estado(empresa, config, _sire_periodos(db, config, empresa.id))


@router.get("/empresas/{empresa_id}/liquidacion/calculo", response_model=LiquidacionCalculoResponse)
def ver_calculo(
    empresa_id: str,
    periodo: str = Query(pattern=PATRON_PERIODO),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    calculo = calcular_periodo(db, empresa, periodo)
    motivo = MOTIVOS_CONFIG.get(_estado_config(db, empresa))
    return {
        **calculo,
        "atencion": ([motivo] if motivo else []) + calculo["atencion"],
        "revisado": _revisiones(db, [empresa.id], periodo).get(empresa.id),
        "puede_revisar": _puede_leer(empresa, usuario),
    }


@router.post("/empresas/{empresa_id}/liquidacion/revisado", response_model=LiquidacionRevisadoItem)
def marcar_revisado(
    empresa_id: str,
    datos: LiquidacionPeriodoRequest,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    """Marca "Revisado" (4.9): el responsable o un admin; se puede marcar varias veces y vale la ultima."""
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    if not _puede_leer(empresa, usuario):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el responsable asignado o un administrador puede marcarla como revisada.")
    _evento(db, empresa.id, usuario, "revisado", datos.periodo)
    db.commit()
    return _revisiones(db, [empresa.id], datos.periodo)[empresa.id]


@router.put("/empresas/{empresa_id}/liquidacion/ventas-proyectadas", response_model=LiquidacionCalculoResponse)
def escribir_ventas_proyectadas(
    empresa_id: str,
    datos: LiquidacionVentasRequest,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    """
    Ventas netas del mes en curso que espera el responsable (p. ej. lo que
    avisa el cliente): la proyeccion del IGV y de la Renta sale de ellas.
    Sin monto vuelve a las calculadas. Devuelve el calculo ya rehecho.
    """
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    if not _puede_leer(empresa, usuario):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el responsable asignado o un administrador puede escribir las ventas proyectadas.")
    if datos.periodo != hoy_peru().strftime("%Y-%m"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Las ventas proyectadas son solo del mes en curso.")
    monto = "" if datos.monto is None else str(datos.monto)
    _evento(db, empresa.id, usuario, ACCION_VENTAS_ESCRITAS, f"{datos.periodo}:{monto}")
    db.commit()
    return ver_calculo(empresa_id, datos.periodo, db, usuario)


@router.get("/empresas/{empresa_id}/liquidacion/serie", response_model=LiquidacionSerieResponse)
def ver_serie(
    empresa_id: str,
    periodo: str = Query(pattern=PATRON_PERIODO),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    """El mes dia a dia, para el grafico del tablero."""
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    return {"periodo": periodo, "puntos": serie_diaria(db, empresa, periodo, hoy_peru())}


@router.get("/liquidacion/panel", response_model=LiquidacionPanelResponse)
def panel_liquidacion(
    periodo: str = Query(pattern=PATRON_PERIODO),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    """El estimado del periodo de cada empresa activada que el usuario ve, por vencimiento (columnas de 4.7)."""
    empresas = _empresas_del_panel(db, usuario)
    revisiones = _revisiones(db, [e.id for e in empresas], periodo)
    hoy = hoy_peru()
    filas = []
    for empresa in empresas:
        calculo = calcular_periodo(db, empresa, periodo, hoy)
        lineas = {l["casilla"]: l for l in calculo["lineas_igv"] + calculo["lineas_renta"] if l["casilla"]}
        estado_config = _estado_config(db, empresa)
        motivo = MOTIVOS_CONFIG.get(estado_config)
        filas.append({
            "empresa_id": empresa.id,
            "ruc": empresa.ruc,
            "razon_social": empresa.razon_social,
            "regimen": calculo["regimen"],
            "responsable_nombre": _nombre(empresa.asignado_a),
            "vence": calculo["vence"],
            "hay_datos": calculo["hay_datos"],
            "datos_al": calculo["datos_al"],
            "lectura_sire": calculo["fechas"].get("sire"),
            "igv_por_pagar": calculo["igv_por_pagar"],
            "saldo_a_favor": calculo["saldo_a_favor"],
            "igv_681": calculo["casillas"]["681"],
            "igv_anio_anterior": calculo["comparacion"][0]["igv"],
            "proyeccion": calculo["proyeccion"],
            "renta_por_pagar": calculo["renta_por_pagar"],
            "avisos": len(calculo["avisos"]),
            "declarado": calculo["declarado"] is not None,
            "igv_declarado": lineas["681"]["declarado"],
            "renta_declarada": lineas["312"]["declarado"],
            "estado_config": estado_config,
            "estado_mes": calculo["estado_mes"],
            "atencion": ([motivo] if motivo else []) + calculo["atencion"],
            "revisado": revisiones.get(empresa.id),
        })
    filas.sort(key=lambda f: (f["vence"] is None, f["vence"] or date.max, f["razon_social"]))
    return {"periodo": periodo, "empresas": filas}


def _empresas_del_panel(db: Session, usuario: Usuario) -> list[Empresa]:
    return (
        filtrar_empresas_visibles(db.query(Empresa), usuario)
        .join(LiquidacionEmpresa, LiquidacionEmpresa.empresa_id == Empresa.id)
        .filter(Empresa.activo.is_(True), LiquidacionEmpresa.activa.is_(True))
        .all()
    )


@router.post("/liquidacion/panel/actualizar", response_model=LiquidacionActualizarResponse)
def actualizar_panel(
    datos: LiquidacionPeriodoRequest,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    """
    "Actualizar todas" del boceto (solo admin): el SIRE y Aduanas del periodo
    de cada empresa activada, espaciadas como la lectura de madrugada. El Menu
    SOL no: entra con la clave de cada empresa y ya tiene sus dias programados.
    """
    if not es_admin(usuario):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo un administrador puede actualizar todas las empresas.")
    if datos.periodo > hoy_peru().strftime("%Y-%m"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ese periodo todavía no empieza.")
    con_clave = {eid for (eid,) in db.query(CredencialSol.empresa_id)}
    encoladas = saltadas = 0
    for empresa in sorted(_empresas_del_panel(db, usuario), key=lambda e: e.razon_social):
        if empresa.id not in con_clave or lecturas_en_curso(db, empresa.id, datetime.now(timezone.utc)):
            saltadas += 1
            continue
        config = db.get(LiquidacionEmpresa, empresa.id)
        fuentes = {"aduanas": (datos.periodo, datos.periodo)}
        if config.api_client_id and config.api_secret_cifrado:
            fuentes["sire"] = (datos.periodo, datos.periodo)
        lecturas = crear_lecturas(db, empresa.id, usuario.id, datos.periodo, list(fuentes), rangos=fuentes)
        db.commit()
        encolar_lecturas(lecturas, espera=timedelta(seconds=encoladas * ESPACIADO_AUTOMATICO_SEG))
        encoladas += 1
    return {"encoladas": encoladas, "saltadas": saltadas, "minutos": math.ceil(encoladas * ESPACIADO_AUTOMATICO_SEG / 60)}


# --- Fase 5: revision de compras y credito fiscal (app/credito_compras.py) ---


def _compras(db: Session, empresa: Empresa, usuario: Usuario, periodo: str) -> dict:
    C = LiquidacionComprobante
    compras = db.query(C).filter(
        C.empresa_id == empresa.id, C.libro == "RCE", C.fuente == "propuesta", C.periodo == periodo,
    ).all()
    revision = RevisionCompras(db, empresa.id, empresa.ruc, hoy_peru()).del_periodo(periodo, compras)
    reglas = (
        db.query(LiquidacionReglaProveedor, Usuario)
        .outerjoin(Usuario, Usuario.id == LiquidacionReglaProveedor.usuario_id)
        .filter(LiquidacionReglaProveedor.empresa_id == empresa.id, LiquidacionReglaProveedor.activa.is_(True))
        .order_by(LiquidacionReglaProveedor.creado_en.desc())
    )
    leida = db.query(LiquidacionLectura.id).filter(
        LiquidacionLectura.empresa_id == empresa.id, LiquidacionLectura.fuente == "sire",
        LiquidacionLectura.estado == "completado", LiquidacionLectura.periodo_desde <= periodo,
        LiquidacionLectura.periodo_hasta >= periodo,
    ).first()
    return {
        "periodo": periodo,
        "razon_social": empresa.razon_social,
        "hay_compras": leida is not None,
        "resumen": {**revision["resumen"], "detracciones_al": revision["detracciones_al"]},
        "grupos": revision["grupos"],
        "filas": revision["filas"],
        "reglas": [
            {
                "id": r.id, "ruc_proveedor": r.ruc_proveedor, "nombre_proveedor": r.nombre_proveedor, "regla": r.regla,
                "desde_periodo": r.desde_periodo, "motivo": r.motivo, "usuario_nombre": _nombre(u) or "", "creado_en": r.creado_en,
            }
            for r, u in reglas
        ],
        "motivos": list(MOTIVOS_COMPRA),
        "puede_decidir": _puede_leer(empresa, usuario),
    }


@router.get("/empresas/{empresa_id}/liquidacion/compras", response_model=LiquidacionComprasResponse)
def ver_compras(
    empresa_id: str,
    periodo: str = Query(pattern=PATRON_PERIODO),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    """Pantalla 3 del boceto: cada compra del registro cruzada con sus depositos de detraccion."""
    return _compras(db, obtener_empresa_visible(empresa_id, usuario, db), usuario, periodo)


@router.put("/empresas/{empresa_id}/liquidacion/compras/{car}", response_model=LiquidacionComprasResponse)
def decidir_compra(
    empresa_id: str,
    car: str,
    datos: LiquidacionCompraDecisionRequest,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    """
    Lo que decide el responsable sobre una compra (5.9): si lleva detraccion y
    si su IGV entra al credito, con motivo. "siempre" y "excluir_siempre" crean
    ademas la regla del proveedor (5.10), desde el periodo de la compra. No
    cambia el registro en SUNAT.
    """
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    if not _puede_leer(empresa, usuario):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el responsable asignado o un administrador puede decidir sobre las compras.")
    compra = db.query(LiquidacionComprobante).filter(
        LiquidacionComprobante.empresa_id == empresa.id, LiquidacionComprobante.libro == "RCE",
        LiquidacionComprobante.car_sunat == car,
    ).first()
    if compra is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No se encontró esa compra.")
    if datos.credito != "auto" and not datos.motivo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Elige un motivo para incluir o excluir la compra.")
    if datos.motivo and datos.motivo not in MOTIVOS_COMPRA:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ese motivo no está en la lista.")
    if datos.motivo == "Otro" and not datos.comentario.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Con el motivo «Otro» escribe un comentario.")
    ruc = (compra.doc_contraparte or "").strip()
    for pedido, regla in (("siempre", "lleva_detraccion"), ("excluir_siempre", "excluir")):
        if pedido in (datos.lleva, datos.credito) and not db.query(LiquidacionReglaProveedor.id).filter(
            LiquidacionReglaProveedor.empresa_id == empresa.id, LiquidacionReglaProveedor.ruc_proveedor == ruc,
            LiquidacionReglaProveedor.regla == regla, LiquidacionReglaProveedor.activa.is_(True),
        ).first():
            db.add(LiquidacionReglaProveedor(
                empresa_id=empresa.id, ruc_proveedor=ruc, nombre_proveedor=(compra.nombre_contraparte or "")[:200], regla=regla,
                desde_periodo=compra.periodo, motivo=" · ".join(x for x in (datos.motivo, datos.comentario.strip()) if x)[:500],
                usuario_id=usuario.id,
            ))
            _evento(db, empresa.id, usuario, "regla_proveedor", f"{regla}:{ruc}")
    db.add(LiquidacionCompraDecision(
        empresa_id=empresa.id, car_sunat=car, periodo=compra.periodo,
        lleva="si" if datos.lleva == "siempre" else datos.lleva,
        credito="excluir" if datos.credito == "excluir_siempre" else datos.credito,
        motivo=datos.motivo, comentario=datos.comentario.strip(), constancia=datos.constancia.strip(), usuario_id=usuario.id,
    ))
    _evento(db, empresa.id, usuario, "decision_compra", f"{compra.periodo}:{car}:{datos.lleva}:{datos.credito}")
    db.commit()
    return _compras(db, empresa, usuario, datos.periodo)


@router.delete("/empresas/{empresa_id}/liquidacion/reglas-proveedor/{regla_id}", response_model=LiquidacionComprasResponse)
def quitar_regla_proveedor(
    empresa_id: str,
    regla_id: str,
    periodo: str = Query(pattern=PATRON_PERIODO),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    """Deshace una regla del proveedor (5.10): queda inactiva, con quien y cuando."""
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    if not _puede_leer(empresa, usuario):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el responsable asignado o un administrador puede quitar reglas.")
    regla = db.get(LiquidacionReglaProveedor, regla_id)
    if regla is None or regla.empresa_id != empresa.id or not regla.activa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No se encontró esa regla.")
    regla.activa = False
    regla.quitada_por_usuario_id = usuario.id
    regla.quitada_en = datetime.now(timezone.utc)
    _evento(db, empresa.id, usuario, "regla_proveedor_quitada", f"{regla.regla}:{regla.ruc_proveedor}")
    db.commit()
    return _compras(db, empresa, usuario, periodo)


@router.post("/empresas/{empresa_id}/liquidacion/compras/historial", status_code=status.HTTP_202_ACCEPTED)
def leer_historial_compras(
    empresa_id: str,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_actual),
):
    """
    Lee del SIRE los 12 meses anteriores (ventas y compras, un pedido por
    minuto): hacen falta para ver las detracciones depositadas tarde y las
    suspendidas.
    """
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    if not _puede_leer(empresa, usuario):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el responsable asignado o un administrador puede pedir lecturas.")
    config = db.get(LiquidacionEmpresa, empresa.id)
    if config is None or not config.api_client_id or not config.api_secret_cifrado:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Falta configurar la API del SIRE de esta empresa.")
    if lecturas_en_curso(db, empresa.id, datetime.now(timezone.utc)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya hay una lectura en curso para esta empresa.")
    actual = hoy_peru().strftime("%Y-%m")
    rango = (sumar_meses(actual, -MESES_ATRAS), sumar_meses(actual, -1))
    lecturas = crear_lecturas(db, empresa.id, usuario.id, rango[1], ["sire"], rangos={"sire": rango})
    _evento(db, empresa.id, usuario, "historial_compras", f"{rango[0]}:{rango[1]}")
    db.commit()
    encolar_lecturas(lecturas)
    return {"desde": rango[0], "hasta": rango[1]}
