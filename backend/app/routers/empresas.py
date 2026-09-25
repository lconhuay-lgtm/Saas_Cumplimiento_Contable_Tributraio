"""CRUD de empresas (RUC monitoreados) dentro del tenant del usuario autenticado."""
import io
import os
import html
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Empresa, CredencialSol, MensajeBuzon, ConsultaJob, Usuario
from app.schemas import (
    EmpresaCreate,
    EmpresaResponse,
    EmpresaUpdate,
    EmpresaCredencialesUpdate,
    ImportarEmpresasResponse,
    EmpresaImportadaItem,
    UltimoMensajeResumen,
)
from app.security import cifrar_clave_sol, descifrar_clave_sol, crear_token_ingreso_directo, decodificar_token
from app.rate_limit import adquirir_slot_global, liberar_slot_global, verificar_limite_ruc, LimiteExcedido
from app.queue_conn import cola_consultas
from app.jobs import ejecutar_consulta_buzon
from app.deps import get_usuario_actual
from app.acceso import filtrar_empresas_visibles, obtener_empresa_visible, es_admin

# Mismo espaciado que "Consultar todas" (ver routers/consultas.py) -- se
# repite aca en vez de importarlo para no crear una dependencia cruzada
# entre routers por una sola constante.
ESPACIADO_IMPORTACION_SEG = 45

logger = logging.getLogger("app.routers.empresas")

router = APIRouter(prefix="/empresas", tags=["empresas"])


def _con_estadisticas(empresas: list[Empresa], db: Session) -> list[EmpresaResponse]:
    if not empresas:
        return []
    ids = [e.id for e in empresas]

    filas_pendientes = (
        db.query(MensajeBuzon.empresa_id, func.count(MensajeBuzon.id))
        .filter(MensajeBuzon.empresa_id.in_(ids), MensajeBuzon.leido.is_(False))
        .group_by(MensajeBuzon.empresa_id)
        .all()
    )
    pendientes_por_empresa = {empresa_id: total for empresa_id, total in filas_pendientes}

    filas_mensajes = (
        db.query(MensajeBuzon.empresa_id, func.count(MensajeBuzon.id))
        .filter(MensajeBuzon.empresa_id.in_(ids))
        .group_by(MensajeBuzon.empresa_id)
        .all()
    )
    mensajes_por_empresa = {empresa_id: total for empresa_id, total in filas_mensajes}

    filas_consultas = (
        db.query(ConsultaJob.empresa_id, func.count(ConsultaJob.id))
        .filter(ConsultaJob.empresa_id.in_(ids))
        .group_by(ConsultaJob.empresa_id)
        .all()
    )
    consultas_por_empresa = {empresa_id: total for empresa_id, total in filas_consultas}

    inicio_de_hoy = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    filas_hoy = (
        db.query(MensajeBuzon.empresa_id, func.count(MensajeBuzon.id))
        .filter(MensajeBuzon.empresa_id.in_(ids), MensajeBuzon.descubierto_en >= inicio_de_hoy)
        .group_by(MensajeBuzon.empresa_id)
        .all()
    )
    mensajes_hoy_por_empresa = {empresa_id: total for empresa_id, total in filas_hoy}

    mensajes_ordenados = (
        db.query(MensajeBuzon)
        .filter(MensajeBuzon.empresa_id.in_(ids))
        .order_by(MensajeBuzon.empresa_id, MensajeBuzon.fecha_publicacion.desc())
        .all()
    )
    ultimo_mensaje_por_empresa: dict[str, MensajeBuzon] = {}
    for m in mensajes_ordenados:
        if m.empresa_id not in ultimo_mensaje_por_empresa:
            ultimo_mensaje_por_empresa[m.empresa_id] = m

    resultado = []
    for e in empresas:
        r = EmpresaResponse.model_validate(e)
        r.pendientes = pendientes_por_empresa.get(e.id, 0)
        r.total_mensajes = mensajes_por_empresa.get(e.id, 0)
        r.total_consultas = consultas_por_empresa.get(e.id, 0)
        r.mensajes_hoy = mensajes_hoy_por_empresa.get(e.id, 0)
        ultimo = ultimo_mensaje_por_empresa.get(e.id)
        if ultimo:
            r.ultimo_mensaje = UltimoMensajeResumen(
                id=ultimo.id,
                asunto=ultimo.asunto,
                tipo=ultimo.tipo,
                tiene_documento=ultimo.documento_ref is not None,
                fecha_publicacion=ultimo.fecha_publicacion,
            )
        resultado.append(r)
    return resultado


@router.get("", response_model=list[EmpresaResponse])
def listar_empresas(
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresas = (
        filtrar_empresas_visibles(db.query(Empresa), usuario)
        .order_by(Empresa.creado_en.desc())
        .all()
    )
    return _con_estadisticas(empresas, db)


@router.get("/{empresa_id}", response_model=EmpresaResponse)
def obtener_empresa(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    return _con_estadisticas([empresa], db)[0]


@router.post("", response_model=EmpresaResponse, status_code=status.HTTP_201_CREATED)
def crear_empresa(
    data: EmpresaCreate,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    existente = (
        db.query(Empresa)
        .filter(Empresa.tenant_id == usuario.tenant_id, Empresa.ruc == data.ruc)
        .first()
    )
    if existente:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese RUC ya esta registrado en tu cuenta")

    empresa = Empresa(
        tenant_id=usuario.tenant_id,
        ruc=data.ruc,
        razon_social=data.razon_social,
        # Un miembro (no admin) que crea una empresa se la auto-asigna --
        # si no, quedaria "sin asignar" y el mismo que la acaba de crear no
        # podria volver a verla (un miembro solo ve lo que tiene asignado).
        asignado_a_usuario_id=None if es_admin(usuario) else usuario.id,
    )
    db.add(empresa)
    db.flush()

    clave_cifrada, dek_cifrada = cifrar_clave_sol(data.clave_sol)
    credencial = CredencialSol(
        empresa_id=empresa.id,
        usuario_sol=data.usuario_sol,
        clave_cifrada=clave_cifrada,
        dek_cifrada=dek_cifrada,
    )
    db.add(credencial)
    db.commit()
    db.refresh(empresa)

    _encolar_consulta_automatica(empresa, usuario, db)

    return empresa


def _encolar_consulta_automatica(empresa: Empresa, usuario: Usuario, db: Session) -> None:
    """
    A pedido: al agregar una empresa nueva, consultarla en vivo enseguida
    en vez de dejarla "vacia" hasta que alguien se acuerde de apretar
    "Consultar" a mano -- asi el usuario ya tiene mensajes reales para
    mapear la empresa desde el primer momento. Una consulta normal ya trae
    hasta 20 mensajes (el limite de siempre, ver adapter.consultar_buzon),
    mas que suficiente para eso -- no hace falta un modo especial de
    "primera consulta".

    Nunca debe tumbar la creacion de la empresa en si: si el RUC choca con
    el limite por-RUC (caso extremadamente raro para un RUC recien creado,
    solo pasaria si se borro y se volvio a crear el mismo RUC segundos
    antes) simplemente no se encola nada, la empresa queda creada igual.
    """
    try:
        verificar_limite_ruc(empresa.ruc)
    except LimiteExcedido:
        logger.info(f"Consulta automatica omitida para {empresa.ruc} (limite por RUC, caso raro para una empresa nueva)")
        return

    job = ConsultaJob(empresa_id=empresa.id, solicitado_por=usuario.id, estado="pendiente")
    db.add(job)
    db.commit()
    db.refresh(job)
    cola_consultas.enqueue(ejecutar_consulta_buzon, job.id, job_timeout="10m")


def _limpiar_ruc(valor) -> str:
    if pd.isna(valor):
        return ""
    if isinstance(valor, float):
        return str(int(valor))
    return str(valor).strip()


def _detectar_columnas(df: pd.DataFrame) -> dict:
    columnas = {}
    for col in df.columns:
        if not isinstance(col, str):
            continue
        cl = col.lower()
        if "ruc" in cl and "ruc" not in columnas:
            columnas["ruc"] = col
        elif ("usuario" in cl or "user" in cl) and "usuario" not in columnas:
            columnas["usuario"] = col
        elif ("clave" in cl or "password" in cl or "contraseña" in cl or "contrasena" in cl) and "clave" not in columnas:
            columnas["clave"] = col
        elif ("contribuyente" in cl or "razon" in cl) and "razon_social" not in columnas:
            columnas["razon_social"] = col
    faltantes = [c for c in ("ruc", "usuario", "clave") if c not in columnas]
    if faltantes:
        raise ValueError(
            f"No se pudieron identificar las columnas {faltantes} en el Excel. "
            "Se esperan columnas con 'RUC', 'usuario', y 'clave'/'contraseña' en el nombre."
        )
    return columnas


@router.post("/importar", response_model=ImportarEmpresasResponse)
async def importar_empresas(
    archivo: UploadFile = File(...),
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    contenido = await archivo.read()
    try:
        df = pd.read_excel(io.BytesIO(contenido), sheet_name=0)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"No se pudo leer el archivo: {e}")

    try:
        columnas = _detectar_columnas(df)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    detalle: list[EmpresaImportadaItem] = []
    creadas = ya_existian = con_error = 0

    for _, fila in df.iterrows():
        try:
            ruc = _limpiar_ruc(fila[columnas["ruc"]])
            if not ruc:
                continue
            if not (ruc.isdigit() and len(ruc) == 11):
                raise ValueError(f"'{ruc}' no es un RUC valido (deben ser 11 digitos)")

            razon_social = (
                str(fila[columnas["razon_social"]]).strip() if "razon_social" in columnas else ruc
            )
            usuario_sol = str(fila[columnas["usuario"]]).strip()
            clave_sol = str(fila[columnas["clave"]]).strip()
            if not usuario_sol or not clave_sol:
                raise ValueError("Usuario o clave SOL vacios")

            existente = (
                db.query(Empresa)
                .filter(Empresa.tenant_id == usuario.tenant_id, Empresa.ruc == ruc)
                .first()
            )
            if existente:
                ya_existian += 1
                detalle.append(EmpresaImportadaItem(ruc=ruc, razon_social=razon_social, resultado="ya_existia"))
                continue

            empresa = Empresa(
                tenant_id=usuario.tenant_id,
                ruc=ruc,
                razon_social=razon_social,
                # Mismo motivo que en crear_empresa(): un miembro que importa
                # se auto-asigna cada fila, si no quedarian invisibles para
                # el mismo apenas terminada la importacion.
                asignado_a_usuario_id=None if es_admin(usuario) else usuario.id,
            )
            db.add(empresa)
            db.flush()

            clave_cifrada, dek_cifrada = cifrar_clave_sol(clave_sol)
            db.add(CredencialSol(
                empresa_id=empresa.id,
                usuario_sol=usuario_sol,
                clave_cifrada=clave_cifrada,
                dek_cifrada=dek_cifrada,
            ))
            db.commit()

            # A pedido: igual que crear_empresa() de a una, pero espaciadas
            # (mismo patron que "Consultar todas") para no mandarle a SUNAT
            # una rafaga de decenas de logins de golpe. Un fallo encolando
            # NUNCA debe marcar la fila como error -- la empresa ya quedo
            # creada bien, el usuario siempre puede apretar "Consultar" a
            # mano despues si esto no llegara a dispararse.
            try:
                job = ConsultaJob(empresa_id=empresa.id, solicitado_por=usuario.id, estado="pendiente")
                db.add(job)
                db.commit()
                db.refresh(job)
                cola_consultas.enqueue_in(
                    timedelta(seconds=creadas * ESPACIADO_IMPORTACION_SEG),
                    ejecutar_consulta_buzon,
                    job.id,
                    job_timeout="10m",
                )
            except Exception as e:
                logger.warning(f"No se pudo encolar la consulta automatica para {ruc} recien importado: {e}")

            creadas += 1
            detalle.append(EmpresaImportadaItem(ruc=ruc, razon_social=razon_social, resultado="creada"))

        except Exception as e:
            db.rollback()
            con_error += 1
            ruc_mostrado = str(fila.get(columnas.get("ruc"), "?")).strip()
            logger.warning(f"Error importando fila (RUC {ruc_mostrado}): {e}")
            detalle.append(EmpresaImportadaItem(ruc=ruc_mostrado, razon_social="", resultado="error", detalle=str(e)))

    return ImportarEmpresasResponse(creadas=creadas, ya_existian=ya_existian, con_error=con_error, detalle=detalle)


@router.patch("/{empresa_id}", response_model=EmpresaResponse)
def actualizar_empresa(
    empresa_id: str,
    data: EmpresaUpdate,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    empresa.activo = data.activo
    if data.es_canario is not None:
        empresa.es_canario = data.es_canario
    if data.es_buen_contribuyente is not None:
        empresa.es_buen_contribuyente = data.es_buen_contribuyente
    # Cartera: a diferencia de los campos de arriba, None es un valor VALIDO
    # aca ("desasignar"), asi que "no vino en el request" y "vino como null"
    # tienen que distinguirse con model_fields_set en vez del chequeo
    # `is not None` que ya usan es_canario/es_buen_contribuyente. Reasignar
    # es admin-only -- un miembro no debe poder darse a si mismo (u otro)
    # acceso a una empresa tocando este campo.
    if "asignado_a_usuario_id" in data.model_fields_set:
        if not es_admin(usuario):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo un admin puede reasignar la cartera de una empresa",
            )
        nuevo_asignado_id = data.asignado_a_usuario_id
        if nuevo_asignado_id is not None:
            asignado = (
                db.query(Usuario)
                .filter(Usuario.id == nuevo_asignado_id, Usuario.tenant_id == usuario.tenant_id)
                .first()
            )
            if not asignado:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El usuario a asignar no existe o no pertenece a este tenant",
                )
        empresa.asignado_a_usuario_id = nuevo_asignado_id
    db.commit()
    db.refresh(empresa)
    return _con_estadisticas([empresa], db)[0]


@router.patch("/{empresa_id}/credenciales", response_model=EmpresaResponse)
def actualizar_credenciales_empresa(
    empresa_id: str,
    data: EmpresaCredencialesUpdate,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Cambiar el usuario/clave SOL guardados -- por ejemplo cuando el cliente
    cambio su clave en SUNAT y las consultas empiezan a fallar por
    credenciales invalidas. Re-cifra de cero (nueva DEK, igual que al crear
    la empresa) en vez de reusar la DEK vieja -- mas simple y sigue el
    mismo patron de "una DEK al azar por operacion de cifrado".
    """
    empresa = obtener_empresa_visible(empresa_id, usuario, db)

    credencial = db.query(CredencialSol).filter(CredencialSol.empresa_id == empresa.id).first()
    if not credencial:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Esta empresa no tiene credenciales SOL guardadas")

    clave_cifrada, dek_cifrada = cifrar_clave_sol(data.clave_sol)
    credencial.usuario_sol = data.usuario_sol
    credencial.clave_cifrada = clave_cifrada
    credencial.dek_cifrada = dek_cifrada
    db.commit()
    db.refresh(empresa)
    return _con_estadisticas([empresa], db)[0]


@router.delete("/{empresa_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_empresa(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    empresa = obtener_empresa_visible(empresa_id, usuario, db)
    db.delete(empresa)
    db.commit()


@router.post("/ingreso-directo/prewarm", status_code=status.HTTP_202_ACCEPTED)
def prewarm_ingreso_directo(usuario: Usuario = Depends(get_usuario_actual)):
    """
    Dispara EN SEGUNDO PLANO un descubrimiento de ingreso directo para
    dejarlo listo en el cache (ver app/ingreso_directo_cache.py) -- el
    frontend llama esto apenas se abre la lista de empresas, asi que para
    cuando el usuario haga clic en "Ir a SUNAT" (segundos o minutos
    despues) haya buenas chances de que ya exista un ticket fresco
    esperando y el clic sea casi instantaneo, en vez de tener que esperar
    los 10-20 segundos que tarda abrir Chrome y llegar a la pantalla de
    login. No requiere que el llamador espere nada (fire and forget) -- si
    el prewarm falla o no llega a tiempo, GET /{empresa_id}/ingreso-directo
    simplemente hace el descubrimiento en vivo, como si este endpoint no
    existiera.
    """
    from app.ingreso_directo_cache import prewarm_ingreso_directo_job

    cola_consultas.enqueue(prewarm_ingreso_directo_job, job_timeout="2m")
    return {"encolado": True}


@router.post("/{empresa_id}/ingreso-directo/token")
def crear_token_para_ingreso_directo(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Paso 1 del "ingreso directo a SUNAT" (abrir una pestaña ya logueada en
    Operaciones en Linea, sin escribir nada -- ver GET
    /{empresa_id}/ingreso-directo mas abajo para el detalle completo del
    mecanismo). El frontend llama esto autenticado como cualquier otro
    endpoint, y con el token que devuelve abre la pestaña nueva -- una
    navegacion comun del navegador no manda el header Authorization, por
    eso hace falta este paso intermedio.
    """
    empresa = obtener_empresa_visible(empresa_id, usuario, db)

    tiene_credencial = db.query(CredencialSol.id).filter(CredencialSol.empresa_id == empresa.id).first()
    if not tiene_credencial:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta empresa no tiene credenciales SOL guardadas")

    token = crear_token_ingreso_directo(usuario.id, usuario.tenant_id, empresa.id)
    return {"token": token}


@router.post("/{empresa_id}/ingreso-directo-declaraciones/token")
def crear_token_para_ingreso_directo_declaraciones(
    empresa_id: str,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Igual que crear_token_para_ingreso_directo, pero para el boton "Ir a
    Declaraciones y Pagos" -- scope propio (ingreso_directo_declaraciones)
    para que este token no sirva para entrar al Menu SOL clasico ni
    viceversa. Ver GET /{empresa_id}/ingreso-directo-declaraciones.
    """
    empresa = obtener_empresa_visible(empresa_id, usuario, db)

    tiene_credencial = db.query(CredencialSol.id).filter(CredencialSol.empresa_id == empresa.id).first()
    if not tiene_credencial:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta empresa no tiene credenciales SOL guardadas")

    token = crear_token_ingreso_directo(usuario.id, usuario.tenant_id, empresa.id, scope="ingreso_directo_declaraciones")
    return {"token": token}


@router.get("/{empresa_id}/ingreso-directo", response_class=HTMLResponse)
def ingreso_directo(empresa_id: str, token: str, db: Session = Depends(get_db)):
    """
    Paso 2 (y el que hace el trabajo real): se abre navegando derecho a
    esta URL (con el token del paso 1 como query param) en una pestaña
    nueva.

    Como funciona: corre un login de prueba con Selenium SOLO para llegar
    hasta la pantalla de login de SUNAT SIN identificarse (ver
    adapter.preparar_ingreso_directo / web_navigation.obtener_url_login)
    -- de ahi se sacan la URL real de destino del login (j_security_check)
    y el parametro `state` que SUNAT genera de nuevo en cada sesion.

    Con esos datos se devuelve una pagina HTML con un formulario oculto,
    ya lleno con el RUC/usuario/clave de esta empresa (los mismos nombres
    de campo del login real: tipo/custom_ruc/j_username/j_password/state/
    originalUrl/lang, confirmados leyendo el codigo fuente de la pantalla
    real de SUNAT), que se autoenvia apenas carga. Clave: es el NAVEGADOR
    DEL USUARIO el que manda ese POST a SUNAT -- no este servidor -- asi
    que la sesion que se abre es una sesion real y propia del usuario en
    el dominio de SUNAT, con sus propias cookies. La clave SOL viaja del
    backend al navegador una sola vez, dentro de esta respuesta, nunca
    hacia SUNAT desde aca.
    """
    payload = decodificar_token(token)
    if not payload or payload.get("scope") != "ingreso_directo" or payload.get("empresa_id") != empresa_id:
        return HTMLResponse(
            _pagina_error_ingreso_directo(
                "Este enlace no es valido o ya vencio (dura solo 2 minutos). "
                "Volve al tablero e intenta de nuevo."
            ),
            status_code=400,
        )

    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.tenant_id == payload.get("tenant_id"))
        .first()
    )
    if not empresa:
        return HTMLResponse(_pagina_error_ingreso_directo("Empresa no encontrada."), status_code=404)

    credencial = db.query(CredencialSol).filter(CredencialSol.empresa_id == empresa.id).first()
    if not credencial:
        return HTMLResponse(
            _pagina_error_ingreso_directo("Esta empresa no tiene credenciales SOL guardadas."),
            status_code=400,
        )

    clave_en_claro = descifrar_clave_sol(credencial.clave_cifrada, credencial.dek_cifrada)

    # Primero se revisa si ya hay un ticket "pre-calentado" fresco en cache
    # (ver app/ingreso_directo_cache.py) -- el descubrimiento no depende de
    # que empresa lo use, asi que si el frontend ya disparo un prewarm hace
    # poco (al abrir la lista de empresas), esto evita abrir Chrome de
    # nuevo y responde casi al instante. Si no hay nada fresco cacheado, se
    # cae exactamente al mismo camino de siempre (descubrimiento en vivo).
    from app.ingreso_directo_cache import obtener_ticket_fresco
    resultado = obtener_ticket_fresco()

    if resultado is not None:
        logger.info(f"Ingreso directo para {empresa.ruc}: usando ticket pre-calentado (sin abrir Selenium).")
        # Fix (analisis de "Ir a SUNAT" lento): el ticket es de un solo uso
        # y compartido entre CUALQUIER empresa -- sin esto, el primer clic
        # de la sesion es rapido pero el SIGUIENTE siempre cae al camino
        # lento de abajo, porque nadie vuelve a pedir un prewarm hasta que
        # se recarga la lista de empresas entera. Se encola en segundo
        # plano (no se espera) para que la respuesta de ESTE clic no se
        # demore por esto.
        from app.ingreso_directo_cache import prewarm_ingreso_directo_job
        cola_consultas.enqueue(prewarm_ingreso_directo_job, job_timeout="2m")
    else:
        # Mismo motivo que en el chequeo canario (Fase 3, bug real encontrado
        # el 18/09): esta funcion abre una sesion real de Selenium con
        # headless=False -- necesita una pantalla virtual (Xvfb), y a
        # diferencia del worker, el backend no arranca una por su cuenta.
        display = None
        if not os.environ.get("DISPLAY"):
            from pyvirtualdisplay import Display
            display = Display(visible=False, size=(1600, 1000))
            display.start()

        try:
            # Fix (analisis de "Ir a SUNAT" lento): timeout de espera de
            # cupo mas corto que el default (240s) -- este endpoint
            # responde a un usuario mirando una pestana en blanco en ese
            # momento, no a un job de fondo. Mejor fallar rapido con un
            # mensaje claro (y sugerir el boton manual) que dejarlo
            # colgado hasta 4 minutos.
            adquirir_slot_global(espera_maxima_seg=45)
        except LimiteExcedido as e:
            if display is not None:
                display.stop()
            return HTMLResponse(
                _pagina_error_ingreso_directo(
                    f"{e} Entra a SUNAT de la forma normal (boton 'Ir -- Op. en Linea') mientras tanto."
                ),
                status_code=503,
            )
        try:
            from adapter import preparar_ingreso_directo
            resultado = preparar_ingreso_directo(ruc=empresa.ruc)
        finally:
            liberar_slot_global()
            if display is not None:
                display.stop()

        if not resultado["ok"]:
            logger.error(f"Ingreso directo fallo para {empresa.ruc}: {resultado['error']}")
            return HTMLResponse(
                _pagina_error_ingreso_directo(
                    f"No se pudo preparar el ingreso directo: {resultado['error']}. "
                    "Intenta de nuevo, o entra a SUNAT de la forma normal (boton 'Ir -- Op. en Linea')."
                ),
                status_code=502,
            )

    html_respuesta = _pagina_autoenvio_sunat(
        accion_url=resultado["accion_url"],
        ruc=empresa.ruc,
        usuario_sol=credencial.usuario_sol,
        clave_sol=clave_en_claro,
        state=resultado.get("state"),
        original_url=resultado.get("original_url"),
        lang=resultado.get("lang") or "es-PE",
    )
    return HTMLResponse(html_respuesta)


@router.get("/{empresa_id}/ingreso-directo-declaraciones", response_class=HTMLResponse)
def ingreso_directo_declaraciones(empresa_id: str, token: str, db: Session = Depends(get_db)):
    """
    Igual mecanismo que GET /{empresa_id}/ingreso-directo (ver el
    docstring de esa funcion para el detalle completo de por que es
    seguro -- la clave SOL nunca pasa por este servidor hacia SUNAT, solo
    viaja una vez hacia el navegador del usuario), pero aterriza en "Mis
    Declaraciones y Pagos" en vez del Menu SOL clasico -- usa
    preparar_ingreso_directo_declaraciones() en vez de
    preparar_ingreso_directo(). Sin el cache "pre-calentado" del otro
    endpoint a proposito: es un boton bastante menos usado, no amerita la
    complejidad extra de generalizar ese cache para dos destinos.
    """
    payload = decodificar_token(token)
    if not payload or payload.get("scope") != "ingreso_directo_declaraciones" or payload.get("empresa_id") != empresa_id:
        return HTMLResponse(
            _pagina_error_ingreso_directo(
                "Este enlace no es valido o ya vencio (dura solo 2 minutos). "
                "Volve al tablero e intenta de nuevo."
            ),
            status_code=400,
        )

    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.tenant_id == payload.get("tenant_id"))
        .first()
    )
    if not empresa:
        return HTMLResponse(_pagina_error_ingreso_directo("Empresa no encontrada."), status_code=404)

    credencial = db.query(CredencialSol).filter(CredencialSol.empresa_id == empresa.id).first()
    if not credencial:
        return HTMLResponse(
            _pagina_error_ingreso_directo("Esta empresa no tiene credenciales SOL guardadas."),
            status_code=400,
        )

    clave_en_claro = descifrar_clave_sol(credencial.clave_cifrada, credencial.dek_cifrada)

    display = None
    if not os.environ.get("DISPLAY"):
        from pyvirtualdisplay import Display
        display = Display(visible=False, size=(1600, 1000))
        display.start()

    try:
        adquirir_slot_global(espera_maxima_seg=45)
    except LimiteExcedido as e:
        if display is not None:
            display.stop()
        return HTMLResponse(
            _pagina_error_ingreso_directo(
                f"{e} Entra a SUNAT de la forma normal mientras tanto."
            ),
            status_code=503,
        )
    try:
        from adapter import preparar_ingreso_directo_declaraciones
        resultado = preparar_ingreso_directo_declaraciones(ruc=empresa.ruc)
    finally:
        liberar_slot_global()
        if display is not None:
            display.stop()

    if not resultado["ok"]:
        logger.error(f"Ingreso directo a Declaraciones y Pagos fallo para {empresa.ruc}: {resultado['error']}")
        return HTMLResponse(
            _pagina_error_ingreso_directo(
                f"No se pudo preparar el ingreso a Declaraciones y Pagos: {resultado['error']}. "
                "Intenta de nuevo, o entra a SUNAT de la forma normal."
            ),
            status_code=502,
        )

    html_respuesta = _pagina_autoenvio_sunat(
        accion_url=resultado["accion_url"],
        ruc=empresa.ruc,
        usuario_sol=credencial.usuario_sol,
        clave_sol=clave_en_claro,
        state=resultado.get("state"),
        original_url=resultado.get("original_url"),
        lang=resultado.get("lang") or "es-PE",
    )
    return HTMLResponse(html_respuesta)


def _pagina_autoenvio_sunat(accion_url: str, ruc: str, usuario_sol: str, clave_sol: str, state, original_url, lang: str) -> str:
    """
    Arma el HTML minimo con el formulario oculto que replica exactamente
    lo que hace el boton "Iniciar sesion" del login real de SUNAT --
    mismos nombres de campo (tipo, custom_ruc, j_username, j_password,
    state, originalUrl, lang), confirmados leyendo el codigo fuente real
    de esa pantalla. Se autoenvia con un <script> apenas carga, asi que el
    usuario no ve ni toca nada -- todos los valores se escapan con
    html.escape() antes de insertarlos, para que ningun caracter especial
    en la clave (comillas, < , etc.) pueda romper el HTML.
    """

    def esc(valor) -> str:
        return html.escape(valor or "", quote=True)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Entrando a SUNAT...</title>
<style>
  body {{ font-family: sans-serif; display: flex; align-items: center; justify-content: center;
          height: 100vh; margin: 0; background: #f4f7f6; color: #1e293b; }}
</style>
</head>
<body>
  <p>Entrando a SUNAT...</p>
  <form id="loginDirecto" action="{esc(accion_url)}" method="POST">
    <input type="hidden" name="tipo" value="2">
    <input type="hidden" name="dni" value="">
    <input type="hidden" name="custom_ruc" value="{esc(ruc)}">
    <input type="hidden" name="j_username" value="{esc(usuario_sol)}">
    <input type="hidden" name="j_password" value="{esc(clave_sol)}">
    <input type="hidden" name="captcha" value="">
    <input type="hidden" name="originalUrl" value="{esc(original_url)}">
    <input type="hidden" name="lang" value="{esc(lang)}">
    <input type="hidden" name="state" value="{esc(state)}">
  </form>
  <script>document.getElementById("loginDirecto").submit();</script>
</body>
</html>"""


def _pagina_error_ingreso_directo(mensaje: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><title>No se pudo entrar a SUNAT</title>
<style>
  body {{ font-family: sans-serif; display: flex; align-items: center; justify-content: center;
          height: 100vh; margin: 0; background: #fef2f2; color: #7f1d1d; }}
  .msg {{ max-width: 420px; text-align: center; padding: 24px; }}
</style>
</head>
<body>
  <div class="msg">
    <h2>No se pudo entrar a SUNAT</h2>
    <p>{html.escape(mensaje)}</p>
  </div>
</body>
</html>"""
