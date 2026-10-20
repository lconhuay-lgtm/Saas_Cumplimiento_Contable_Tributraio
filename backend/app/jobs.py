"""
Funcion que RQ ejecuta para consultar el buzon de una empresa y guardar los
mensajes nuevos en la base de datos.
"""
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from app.database import SessionLocal
from app.models import (
    ConsultaJob, FichaRucJob, ReporteTributarioJob, Empresa, CredencialSol, MensajeBuzon, Usuario,
    TareaObligacion, ConsultaSireJob, SireEstadoPeriodo, ConsultaDeudasJob, ValorDeuda,
)
from app.security import descifrar_clave_sol, crear_token_ingreso_directo
from app.rate_limit import adquirir_slot_global, liberar_slot_global, limite_mensajes_por_consulta
from app.almacenamiento import guardar_documento, guardar_documento_bytes, AlmacenamientoError
from app.clasificacion import clasificar_tipo
from app.email_utils import enviar_notificacion_mensajes_nuevos
from app.cronograma_sunat import _PATRONES_SIN_OBLIGACIONES

MAX_INTENTOS = 2
ESPERA_ENTRE_INTENTOS_SEG = 15
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
# Dominio publico del backend -- NEXT_PUBLIC_API_URL ya esta en el .env
# (lo usa el frontend al buildear) y docker-compose lo carga igual en este
# contenedor via env_file, asi que se reusa en vez de pedir una variable
# nueva. Se usa para armar el link directo al PDF en el correo de "mensajes
# nuevos" (ver _notificar_mensajes_nuevos).
API_URL_PUBLICA = os.environ.get("NEXT_PUBLIC_API_URL", "http://localhost:8000")
# Vida del link de documento por correo -- mucho mas larga que los 2
# minutos del token de "ingreso directo a SUNAT" (que se usa al toque, en
# la misma sesion) porque este viaja en un correo que la persona puede
# abrir dias despues, de otro dispositivo, sin haber iniciado sesion ahi.
DURACION_TOKEN_DOCUMENTO_CORREO_MIN = 60 * 24 * 7  # 7 dias

# A pedido: leer el "Estado del Contribuyente" cuesta ~8-10s extra por
# consulta (navega a la Ficha RUC, ver deteccion_estado._leer_estado_contribuyente)
# porque a diferencia de la condicion de domicilio no vive en el navbar
# normal. Con muchas empresas y consultas frecuentes (chequeo automatico
# 11am/7:30pm + "Consultar todas" + consultas manuales) ese costo se repetia
# en CADA corrida sin necesidad real -- el dato rara vez cambia varias veces
# al dia. Se re-verifica como maximo una vez cada VENTANA_ESTADO_CONTRIBUYENTE_HORAS,
# sea cual sea la consulta que dispare el chequeo (no hace falta un cron
# aparte: el primer chequeo automatico del dia, o la primera consulta manual,
# ya lo renueva solo). 20h en vez de 24h a proposito, para tolerar que el
# chequeo automatico de las 11am de un dia y el de las 7:30pm del dia
# anterior no calcen exactos cada 24h.
VENTANA_ESTADO_CONTRIBUYENTE_HORAS = 20

logger = logging.getLogger("app.jobs")


def _mensaje_id(fecha: str, asunto: str) -> str:
    return hashlib.sha256(f"{fecha}|{asunto}".encode("utf-8")).hexdigest()


def _mensaje_id_buzon_mensajes(id_sunat: str) -> str:
    """Mismo criterio que adapter.mensaje_id_buzon_mensajes() -- debe coincidir, si uno cambia el otro tambien."""
    return f"bm-{id_sunat}"


def _parsear_fecha(texto_fecha: str) -> datetime:
    texto_fecha = (texto_fecha or "").strip()
    match = re.match(r"(\d{2})/(\d{2})/(\d{4})\s*(\d{2}):(\d{2}):(\d{2})?", texto_fecha)
    if match:
        dia, mes, anio, hora, minuto, segundo = match.groups()
        try:
            return datetime(
                int(anio), int(mes), int(dia), int(hora), int(minuto), int(segundo or 0),
                tzinfo=timezone.utc,
            )
        except ValueError:
            pass
    logger.warning(f"No se pudo interpretar la fecha '{texto_fecha}', usando la hora actual")
    return datetime.now(timezone.utc)


def _normalizar_nombre(nombre: str) -> str:
    """Mayusculas, sin espacios ni puntos finales -- para comparar nombres
    ignorando diferencias triviales de formato (ver _es_probable_truncamiento)."""
    return (nombre or "").strip().rstrip(".").upper()


def _es_probable_truncamiento(nombre_actual: str, nombre_sunat: str) -> bool:
    """
    True si el nombre que trae SUNAT esta mas corto y parece ser el nombre
    actual con unos pocos caracteres de menos al final, en vez de un
    nombre realmente distinto -- en ese caso conviene MANTENER el nombre
    actual (mas completo) en vez de "corregirlo" por la version recortada.

    Se detecto en produccion (ver sunat_data/logs/sunat_auto_20260918_*.log)
    que el banner "Bienvenido, ..." del Menu SOL a veces devuelve el nombre
    recortado en 1-2 caracteres -- el propio HTML de SUNAT trae un
    comentario "<!--TODO: Truncar-->" junto a ese elemento, señal de que
    ellos mismos le aplican algun recorte por ancho disponible. Sin este
    chequeo, cada consulta futura "corregiria" el nombre completo por la
    version recortada, generando un ping-pong inutil en vez de una
    correccion real.

    Deliberadamente unidireccional: si lo que trae SUNAT es MAS LARGO (o de
    otro modo distinto) que el nombre actual, nunca se considera
    truncamiento -- un recorte de UI solo puede quitar texto, no agregarlo,
    asi que un nombre mas largo/completo de SUNAT siempre es bienvenido.
    """
    actual = _normalizar_nombre(nombre_actual)
    sunat = _normalizar_nombre(nombre_sunat)
    if not actual or not sunat or actual == sunat:
        return False
    if len(sunat) >= len(actual):
        return False
    diferencia = len(actual) - len(sunat)
    if diferencia > 8:
        return False
    return actual.startswith(sunat)


def _notificar_mensajes_nuevos(db, empresa: Empresa, mensajes_info: list[dict]) -> None:
    """
    Correo INMEDIATO por mensajes nuevos (distinto del resumen diario de
    scheduler_job.py, que sigue igual) -- solo se llama cuando la consulta
    que los encontro NO es la de alta inicial de la empresa (ver
    ConsultaJob.es_alta_inicial). Mismo criterio de visibilidad que
    acceso.filtrar_empresas_visibles pero invertido (dada una empresa,
    quien puede verla): todos los admin del tenant, mas el unico miembro
    (si hay) que tiene esta empresa asignada. No se importa acceso.py aca
    porque esa funcion trabaja sobre una Query ya armada con Empresa en el
    FROM -- este es un proceso de worker, no un endpoint.

    mensajes_info: [{"asunto": str, "mensaje_id": str, "tiene_documento": bool}, ...]
    Para los que SI tienen documento, se arma un link directo al PDF con un
    token de un solo proposito (ver crear_token_ingreso_directo en
    security.py, mismo mecanismo que "ingreso directo a SUNAT" mas abajo en
    este archivo, reusado aca con scope="ver_documento") -- asi el correo
    no necesita adjuntar ni pre-cargar ningun PDF (cero trabajo extra para
    el sistema al mandar el correo), y el link sirve sin tener que volver a
    iniciar sesion, incluso dias despues desde otro dispositivo. El PDF se
    lee de storage recien cuando (y si) alguien hace clic, igual que ya
    pasa con el visor normal del tablero -- no hay ninguna carga de mas.

    Nunca debe tumbar el job de consulta si algo sale mal aca (mismo
    criterio que el resto de los envios de correo del sistema).
    """
    try:
        usuarios = (
            db.query(Usuario)
            .filter(Usuario.tenant_id == empresa.tenant_id)
            .filter(Usuario.forma_notificacion == "correo")
            .filter(or_(Usuario.rol == "admin", Usuario.id == empresa.asignado_a_usuario_id))
            .all()
        )
        if not usuarios:
            return
        link_empresa = f"{FRONTEND_URL}/empresas/{empresa.id}"

        for usuario in usuarios:
            items = []
            for m in mensajes_info:
                link_documento = None
                if m["tiene_documento"]:
                    token_doc = crear_token_ingreso_directo(
                        usuario.id, empresa.tenant_id, empresa.id,
                        minutos=DURACION_TOKEN_DOCUMENTO_CORREO_MIN,
                        scope="ver_documento",
                        mensaje_id=m["mensaje_id"],
                    )
                    link_documento = (
                        f"{API_URL_PUBLICA}/empresas/{empresa.id}/mensajes/{m['mensaje_id']}"
                        f"/documento-por-correo?token={token_doc}"
                    )
                items.append({"asunto": m["asunto"], "link_documento": link_documento})
            enviar_notificacion_mensajes_nuevos(usuario.email, empresa.razon_social, empresa.ruc, items, link_empresa)
    except Exception:
        logger.exception(f"No se pudo notificar mensajes nuevos por correo para {empresa.ruc}")


def ejecutar_consulta_buzon(job_id: str):
    db = SessionLocal()

    # Mismo patron (y misma razon) que en ejecutar_generar_ficha_ruc: el
    # UNICO lugar que escribe job.etapa, incluso para "limpiarla" a None,
    # para no caer en la trampa de que SQLAlchemy ignore una asignacion
    # directa que "parece" no cambiar nada desde el punto de vista de la
    # sesion de afuera. Definida ANTES de cualquier otra cosa para que
    # este disponible incluso si algo revienta muy temprano.
    def _reportar_etapa(etapa: str | None):
        db_etapa = SessionLocal()
        try:
            job_actual = db_etapa.query(ConsultaJob).filter(ConsultaJob.id == job_id).first()
            if job_actual:
                job_actual.etapa = etapa
                db_etapa.commit()
        finally:
            db_etapa.close()

    try:
        job = db.query(ConsultaJob).filter(ConsultaJob.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} no encontrado")
            return

        job.estado = "en_progreso"
        job.iniciado_en = datetime.now(timezone.utc)
        db.commit()

        empresa = db.query(Empresa).filter(Empresa.id == job.empresa_id).first()
        credencial = (
            db.query(CredencialSol).filter(CredencialSol.empresa_id == job.empresa_id).first()
            if empresa else None
        )

        if not empresa or not credencial:
            job.estado = "error"
            job.error = "Empresa o credenciales no encontradas"
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
            return

        clave_en_claro = descifrar_clave_sol(credencial.clave_cifrada, credencial.dek_cifrada)

        from adapter import consultar_buzon

        # OJO: esto le dice al scraper que documentos NO hace falta volver a
        # descargar -- por eso se filtra a los que YA tienen documento_ref,
        # no a "todo mensaje que ya conocemos". Un mensaje puede haberse
        # guardado sin PDF porque la corrida anterior toco el limite de
        # MAX_DESCARGAS_POR_CORRIDA (adapter.py) antes de llegar a el -- si
        # aca se incluyera cualquier mensaje ya guardado (tenga o no
        # documento), esa notificacion se quedaria SIN PDF para siempre,
        # porque el chequeo de "mensaje nuevo" mas abajo (`existe`) igual lo
        # va a saltar en cada corrida futura.
        ids_conocidos = {
            fila[0]
            for fila in db.query(MensajeBuzon.mensaje_externo_id)
            .filter(MensajeBuzon.empresa_id == empresa.id, MensajeBuzon.documento_ref.isnot(None))
            .all()
        }

        # Mismo criterio que ids_conocidos arriba, version Buzón Mensajes:
        # solo cuentan como "ya conocidos" los que YA tienen su contenido
        # de texto capturado -- si una corrida anterior guardo el mensaje
        # pero no pudo leer su contenido (ver _leer_contenido_texto_mensaje
        # en adapter.py), se vuelve a intentar en vez de quedarse sin texto
        # para siempre.
        ids_conocidos_buzon_mensajes = {
            fila[0]
            for fila in db.query(MensajeBuzon.mensaje_externo_id)
            .filter(
                MensajeBuzon.empresa_id == empresa.id,
                MensajeBuzon.origen == "mensajes",
                MensajeBuzon.contenido_texto.isnot(None),
            )
            .all()
        }

        # Ver VENTANA_ESTADO_CONTRIBUYENTE_HORAS arriba -- solo se paga el
        # costo extra de entrar a la Ficha RUC si nunca se verifico, o si la
        # ultima verificacion ya paso esa ventana.
        necesita_verificar_estado = (
            empresa.estado_contribuyente_verificado_en is None
            or datetime.now(timezone.utc) - empresa.estado_contribuyente_verificado_en
            >= timedelta(hours=VENTANA_ESTADO_CONTRIBUYENTE_HORAS)
        )

        token_slot = adquirir_slot_global()
        try:
            resultado = None
            for intento in range(1, MAX_INTENTOS + 1):
                resultado = consultar_buzon(
                    ruc=empresa.ruc,
                    usuario_sol=credencial.usuario_sol,
                    clave_sol=clave_en_claro,
                    razon_social=empresa.razon_social,
                    headless=False,
                    limite_mensajes=limite_mensajes_por_consulta(),
                    ids_conocidos=ids_conocidos,
                    ids_conocidos_buzon_mensajes=ids_conocidos_buzon_mensajes,
                    leer_estado_contribuyente=necesita_verificar_estado,
                    on_progreso=_reportar_etapa,
                )
                if resultado["ok"]:
                    break
                logger.warning(
                    f"Intento {intento}/{MAX_INTENTOS} fallo para {empresa.ruc}: {resultado['error']}"
                )
                # Reintentar con una clave que SUNAT ya rechazo no arregla
                # nada y suma intentos fallidos que pueden bloquear el usuario SOL.
                if resultado.get("credenciales_rechazadas"):
                    break
                if intento < MAX_INTENTOS:
                    time.sleep(ESPERA_ENTRE_INTENTOS_SEG * intento)
        finally:
            liberar_slot_global(token_slot)

        # SUNAT es la fuente de verdad del nombre de la empresa -- lo que
        # haya en la base (tipeado a mano o traido de un Excel importado) se
        # corrige con el nombre real apenas se detecta, SIN esperar a que
        # el resto de la consulta termine bien. Se hace ANTES de revisar
        # resultado["ok"] a proposito: el nombre se lee del banner de
        # bienvenida justo despues del login, que puede tener exito aunque
        # un paso posterior (navegar al Buzon Electronico) falle -- perder
        # ese dato ya verificado solo porque el resto de la consulta no
        # llego a buen puerto seria tirar informacion valida a la basura.
        # Comparacion insensible a mayusculas/espacios/punto final, y con
        # una heuristica aparte para ignorar probables truncamientos del
        # propio banner de SUNAT (ver _es_probable_truncamiento).
        razon_social_sunat = (resultado.get("razon_social_sunat") or "").strip()
        nombre_actual = (empresa.razon_social or "").strip()
        if razon_social_sunat and _normalizar_nombre(razon_social_sunat) != _normalizar_nombre(nombre_actual):
            if _es_probable_truncamiento(nombre_actual, razon_social_sunat):
                logger.info(
                    f"Se ignora un probable recorte del banner de SUNAT para {empresa.ruc}: "
                    f"SUNAT mostro '{razon_social_sunat}' pero se mantiene '{nombre_actual}' (mas completo)"
                )
            else:
                logger.info(
                    f"Actualizando razon social de {empresa.ruc} segun SUNAT: "
                    f"'{nombre_actual}' -> '{razon_social_sunat}'"
                )
                empresa.razon_social = razon_social_sunat

        # Condicion del domicilio fiscal -- mismo razonamiento que la razon
        # social (se guarda apenas se detecta, no solo si toda la consulta
        # termina bien). A diferencia de la razon social no hay heuristica
        # de truncamiento: son 2-3 palabras fijas (Habido/No Habido/No
        # Hallado), sin riesgo de recorte por ancho de pantalla.
        condicion_domicilio = (resultado.get("condicion_domicilio") or "").strip()
        if condicion_domicilio and condicion_domicilio != (empresa.condicion_domicilio or ""):
            logger.info(
                f"Actualizando condicion de domicilio de {empresa.ruc}: "
                f"'{empresa.condicion_domicilio}' -> '{condicion_domicilio}'"
            )
            # Solo se registra como "cambio" (para el aviso del Dashboard) si
            # ya habia un valor previo conocido -- la primera vez que se
            # detecta para una empresa no es un cambio, es el punto de
            # partida.
            if empresa.condicion_domicilio is not None:
                empresa.condicion_domicilio_anterior = empresa.condicion_domicilio
                empresa.condicion_domicilio_actualizada_en = datetime.now(timezone.utc)
            empresa.condicion_domicilio = condicion_domicilio

        # Estado del contribuyente (Activo/Baja de Oficio/etc.) -- mismo
        # razonamiento que la condicion de domicilio (se guarda apenas se
        # detecta, y solo cuenta como "cambio" para el aviso del Dashboard
        # si ya habia un valor previo conocido). A diferencia de la
        # condicion de domicilio, este dato se lee entrando a la Ficha RUC
        # (ver core_scraper.web_navigation._leer_estado_contribuyente), no
        # del navbar normal -- confirmado que no aparece ahi con un
        # diagnostico real.
        estado_contribuyente = (resultado.get("estado_contribuyente") or "").strip()
        if estado_contribuyente and estado_contribuyente != (empresa.estado_contribuyente or ""):
            logger.info(
                f"Actualizando estado del contribuyente de {empresa.ruc}: "
                f"'{empresa.estado_contribuyente}' -> '{estado_contribuyente}'"
            )
            if empresa.estado_contribuyente is not None:
                empresa.estado_contribuyente_anterior = empresa.estado_contribuyente
                empresa.estado_contribuyente_actualizado_en = datetime.now(timezone.utc)
            empresa.estado_contribuyente = estado_contribuyente

            # La empresa paso a baja/suspension recien ahora: ya no tiene
            # obligaciones corrientes (mismo criterio que
            # cronograma_sunat._empresas_para_cronograma, que ya evita
            # generarle tareas NUEVAS de aqui en adelante). Pero las tareas
            # automaticas (IGV-Renta/Planilla/etc., proceso="automatica")
            # que ya se habian creado ANTES de este cambio -- de un mes en
            # que la empresa todavia estaba activa -- se quedaban pendientes
            # para siempre y terminaban marcadas como "vencidas" sin que la
            # empresa deba declarar nada. Las tareas manuales (creadas a
            # mano por el usuario, ej. "tramite de cierre") no se tocan.
            if any(patron.strip("%") in estado_contribuyente.upper() for patron in _PATRONES_SIN_OBLIGACIONES):
                tareas_obsoletas = (
                    db.query(TareaObligacion)
                    .filter(
                        TareaObligacion.empresa_id == empresa.id,
                        TareaObligacion.estado == "pendiente",
                        TareaObligacion.proceso == "automatica",
                    )
                    .all()
                )
                if tareas_obsoletas:
                    logger.info(
                        f"{empresa.ruc} paso a '{estado_contribuyente}': se marcan "
                        f"{len(tareas_obsoletas)} tarea(s) automatica(s) pendiente(s) como 'no_aplica'."
                    )
                    for t in tareas_obsoletas:
                        t.estado = "no_aplica"

        # Se actualiza SIEMPRE que esta corrida haya intentado leerlo (haya
        # cambiado el valor o no) -- es lo que decide si la PROXIMA consulta
        # se salta este paso. Distinto de estado_contribuyente_actualizado_en,
        # que solo se toca cuando el valor cambia.
        if resultado.get("estado_contribuyente_verificado"):
            empresa.estado_contribuyente_verificado_en = datetime.now(timezone.utc)

        if not resultado["ok"]:
            job.estado = "error"
            job.error = (resultado["error"] or "Error desconocido")[:1000]
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
            _reportar_etapa(None)
            logger.warning(f"Job {job_id} fallo para {empresa.ruc}: {job.error}")
            return

        nuevos = 0
        asuntos_nuevos = []
        # Referencias a los objetos recien creados (no solo el asunto) --
        # hace falta despues del commit para armar el link de documento por
        # correo (necesita el id real, que el ORM solo asigna al flushear/
        # commitear, no al construir el objeto).
        mensajes_nuevos_objs = []
        documentos_descargados = resultado.get("documentos", {}) or {}
        # Respaldo para mensajes de Buzón Notificaciones que NO traen PDF
        # (confirmado en produccion: algunos tipos, ej. "NOTIFICACION DE LA
        # DECLARACION", solo traen un enlace generico de contacto dentro del
        # mensaje, sin constancia_/goArchivoDescarga) -- sin esto quedaban
        # guardados sin PDF y sin ninguna otra forma de verlos en el
        # tablero. Ver _descargar_documentos_nuevos en core_scraper/adapter.py.
        contenidos_texto_notif = resultado.get("contenidos_texto_notificaciones", {}) or {}
        vistos_en_esta_corrida = set()
        for msg in resultado["mensajes"]:
            mid = _mensaje_id(msg["fecha"], msg["asunto"])
            if mid in vistos_en_esta_corrida:
                continue
            vistos_en_esta_corrida.add(mid)
            existe = (
                db.query(MensajeBuzon)
                .filter(MensajeBuzon.empresa_id == empresa.id, MensajeBuzon.mensaje_externo_id == mid)
                .first()
            )
            if existe:
                # El mensaje ya estaba guardado, pero puede que le faltara
                # el PDF de una corrida anterior (ver el comentario de
                # ids_conocidos mas arriba) -- si esta corrida SI lo logro
                # descargar, hay que completarlo aca, no perderlo.
                if existe.documento_ref is None:
                    ruta_local_pdf = documentos_descargados.get(mid)
                    if ruta_local_pdf:
                        try:
                            existe.documento_ref = guardar_documento(ruta_local_pdf, empresa.id, mid)
                        except AlmacenamientoError as e:
                            logger.error(f"No se pudo guardar el documento del mensaje '{msg['asunto']}': {e}")
                    elif existe.contenido_texto is None:
                        texto_respaldo = contenidos_texto_notif.get(mid)
                        if texto_respaldo:
                            existe.contenido_texto = texto_respaldo
                continue

            documento_ref = None
            ruta_local_pdf = documentos_descargados.get(mid)
            if ruta_local_pdf:
                try:
                    documento_ref = guardar_documento(ruta_local_pdf, empresa.id, mid)
                except AlmacenamientoError as e:
                    logger.error(f"No se pudo guardar el documento del mensaje '{msg['asunto']}': {e}")

            nuevo_mensaje = MensajeBuzon(
                empresa_id=empresa.id,
                mensaje_externo_id=mid,
                fecha_publicacion=_parsear_fecha(msg["fecha"]),
                asunto=msg["asunto"],
                tipo=clasificar_tipo(msg["asunto"]),
                documento_ref=documento_ref,
                contenido_texto=contenidos_texto_notif.get(mid) if documento_ref is None else None,
                notificado_popup=job.es_alta_inicial,
            )
            db.add(nuevo_mensaje)
            nuevos += 1
            asuntos_nuevos.append(msg["asunto"])
            mensajes_nuevos_objs.append(nuevo_mensaje)

        # Buzón Mensajes (bandeja separada de Notificaciones, sin PDF en
        # general -- ver adapter._leer_mensajes_buzon_mensajes). Mismo
        # criterio de dedup e idempotencia que el bucle de arriba, pero
        # usando el id nativo de SUNAT como mensaje_externo_id en vez de un
        # hash fecha+asunto (ver _mensaje_id_buzon_mensajes).
        for msg in resultado.get("mensajes_bandeja", []):
            mid = _mensaje_id_buzon_mensajes(msg["id_sunat"])
            if mid in vistos_en_esta_corrida:
                continue
            vistos_en_esta_corrida.add(mid)
            existe = (
                db.query(MensajeBuzon)
                .filter(MensajeBuzon.empresa_id == empresa.id, MensajeBuzon.mensaje_externo_id == mid)
                .first()
            )
            if existe:
                # Igual que con el PDF arriba: si una corrida anterior no
                # logro leer el contenido, se completa aca en vez de
                # perderlo para siempre.
                if existe.contenido_texto is None and msg.get("contenido_texto"):
                    existe.contenido_texto = msg["contenido_texto"]
                continue

            nuevo_mensaje = MensajeBuzon(
                empresa_id=empresa.id,
                mensaje_externo_id=mid,
                fecha_publicacion=_parsear_fecha(msg["fecha"]),
                asunto=msg["asunto"],
                tipo=clasificar_tipo(msg["asunto"]),
                leido=msg.get("leido", False),
                origen="mensajes",
                contenido_texto=msg.get("contenido_texto"),
                notificado_popup=job.es_alta_inicial,
            )
            db.add(nuevo_mensaje)
            nuevos += 1
            asuntos_nuevos.append(msg["asunto"])
            mensajes_nuevos_objs.append(nuevo_mensaje)

        empresa.ultima_consulta_en = datetime.now(timezone.utc)
        job.estado = "completado"
        job.mensajes_nuevos = nuevos
        job.finalizado_en = datetime.now(timezone.utc)
        db.commit()
        _reportar_etapa(None)
        logger.info(f"Job {job_id} completado: {nuevos} mensajes nuevos para {empresa.ruc}")

        if nuevos > 0 and not job.es_alta_inicial:
            # Recien aca los objetos tienen su id real (el ORM lo asigna al
            # flushear, que ya paso con el commit de arriba).
            info_mensajes_nuevos = [
                {"asunto": m.asunto, "mensaje_id": m.id, "tiene_documento": m.documento_ref is not None}
                for m in mensajes_nuevos_objs
            ]
            _notificar_mensajes_nuevos(db, empresa, info_mensajes_nuevos)

    except Exception as e:
        logger.exception(f"Error ejecutando job {job_id}")
        db.rollback()
        job = db.query(ConsultaJob).filter(ConsultaJob.id == job_id).first()
        if job:
            job.estado = "error"
            job.error = str(e)[:1000]
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
        _reportar_etapa(None)
    finally:
        db.close()


def ejecutar_generar_ficha_ruc(job_id: str):
    """
    Genera el PDF de la Ficha RUC de una empresa (RUC, razon social,
    estado del contribuyente, condicion de domicilio, actividad economica)
    y lo guarda en el mismo almacenamiento que los documentos de mensajes.
    Reemplaza el PDF anterior si ya existia uno (se guarda con un id fijo
    "ficha-ruc" por empresa, a diferencia de los mensajes que se acumulan).
    """
    db = SessionLocal()

    # Callback que el adaptador llama en cada etapa (login, abriendo la
    # ficha, generando el PDF) -- se guarda en el job para que el frontend
    # haga polling y muestre una barra de progreso real en vez de un
    # spinner sin perspectiva de tiempo. Usa su PROPIA sesion de base de
    # datos en cada llamada (no la de afuera) porque corre dentro de la
    # misma llamada sincrona a generar_ficha_ruc_pdf.
    #
    # A proposito es tambien el UNICO lugar del archivo que escribe
    # job.etapa -- incluso para "limpiarla" a None se usa esta misma
    # funcion en vez de asignar job.etapa directo sobre el objeto `job` de
    # la sesion de afuera. Se probo (con un test real) que asignar
    # job.etapa = None directo NO quedaba guardado: SQLAlchemy solo incluye
    # una columna en el UPDATE si detecta que cambio respecto al valor que
    # esa sesion cargo originalmente, y como esa sesion nunca vio el valor
    # que esta funcion escribio por otro lado (p.ej. "guardando"), asignar
    # None -- igual al valor original antes de empezar -- no generaba
    # ningun cambio detectable y la columna quedaba sin tocar en el UPDATE.
    # Pasando SIEMPRE por esta funcion se evita esa trampa por completo.
    # Definida ANTES de cualquier otra cosa para que este disponible incluso
    # si algo revienta muy temprano y se cae al except de mas abajo.
    def _reportar_etapa(etapa: str | None):
        db_etapa = SessionLocal()
        try:
            job_actual = db_etapa.query(FichaRucJob).filter(FichaRucJob.id == job_id).first()
            if job_actual:
                job_actual.etapa = etapa
                db_etapa.commit()
        finally:
            db_etapa.close()

    try:
        job = db.query(FichaRucJob).filter(FichaRucJob.id == job_id).first()
        if not job:
            logger.error(f"FichaRucJob {job_id} no encontrado")
            return

        job.estado = "en_progreso"
        job.iniciado_en = datetime.now(timezone.utc)
        db.commit()

        empresa = db.query(Empresa).filter(Empresa.id == job.empresa_id).first()
        credencial = (
            db.query(CredencialSol).filter(CredencialSol.empresa_id == job.empresa_id).first()
            if empresa else None
        )

        if not empresa or not credencial:
            job.estado = "error"
            job.error = "Empresa o credenciales no encontradas"
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
            return

        clave_en_claro = descifrar_clave_sol(credencial.clave_cifrada, credencial.dek_cifrada)

        from adapter import generar_ficha_ruc_pdf

        token_slot = adquirir_slot_global()
        try:
            resultado = generar_ficha_ruc_pdf(
                ruc=empresa.ruc,
                usuario_sol=credencial.usuario_sol,
                clave_sol=clave_en_claro,
                razon_social=empresa.razon_social,
                headless=False,
                on_progreso=_reportar_etapa,
                con_qr=job.con_qr,
            )
        finally:
            liberar_slot_global(token_slot)

        if not resultado["ok"]:
            job.estado = "error"
            job.error = (resultado["error"] or "Error desconocido")[:1000]
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
            _reportar_etapa(None)
            logger.warning(f"FichaRucJob {job_id} fallo para {empresa.ruc}: {job.error}")
            return

        _reportar_etapa("guardando")
        try:
            referencia = guardar_documento_bytes(
                resultado["pdf_bytes"], empresa.id, "ficha-ruc-qr" if job.con_qr else "ficha-ruc"
            )
        except AlmacenamientoError as e:
            job.estado = "error"
            job.error = f"No se pudo guardar el PDF generado: {e}"[:1000]
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
            _reportar_etapa(None)
            logger.error(f"FichaRucJob {job_id}: {job.error}")
            return

        if job.con_qr:
            empresa.ficha_ruc_qr_pdf_ref = referencia
            empresa.ficha_ruc_qr_generada_en = datetime.now(timezone.utc)
        else:
            empresa.ficha_ruc_pdf_ref = referencia
            empresa.ficha_ruc_generada_en = datetime.now(timezone.utc)
        job.estado = "completado"
        job.finalizado_en = datetime.now(timezone.utc)
        db.commit()
        _reportar_etapa(None)
        logger.info(f"FichaRucJob {job_id} completado para {empresa.ruc}")

    except Exception as e:
        logger.exception(f"Error ejecutando FichaRucJob {job_id}")
        db.rollback()
        job = db.query(FichaRucJob).filter(FichaRucJob.id == job_id).first()
        if job:
            job.estado = "error"
            job.error = str(e)[:1000]
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
        _reportar_etapa(None)
    finally:
        db.close()


def ejecutar_generar_reporte_tributario(job_id: str):
    """
    Solicita el "Reporte Tributario para Terceros" (informacion RESERVADA,
    Art. 85 del Codigo Tributario) de una empresa -- SUNAT lo genera y lo
    manda por su cuenta al correo indicado, asi que a diferencia de
    ejecutar_generar_ficha_ruc este job no descarga ni guarda ningun PDF:
    solo entra, acepta el aviso legal, y confirma el envio.
    """
    db = SessionLocal()

    # Mismo patron (y misma razon) que en ejecutar_generar_ficha_ruc: el
    # UNICO lugar que escribe job.etapa, para que SQLAlchemy detecte el
    # cambio incluso al "limpiarla" a None.
    def _reportar_etapa(etapa: str | None):
        db_etapa = SessionLocal()
        try:
            job_actual = db_etapa.query(ReporteTributarioJob).filter(ReporteTributarioJob.id == job_id).first()
            if job_actual:
                job_actual.etapa = etapa
                db_etapa.commit()
        finally:
            db_etapa.close()

    try:
        job = db.query(ReporteTributarioJob).filter(ReporteTributarioJob.id == job_id).first()
        if not job:
            logger.error(f"ReporteTributarioJob {job_id} no encontrado")
            return

        job.estado = "en_progreso"
        job.iniciado_en = datetime.now(timezone.utc)
        db.commit()

        empresa = db.query(Empresa).filter(Empresa.id == job.empresa_id).first()
        credencial = (
            db.query(CredencialSol).filter(CredencialSol.empresa_id == job.empresa_id).first()
            if empresa else None
        )

        if not empresa or not credencial:
            job.estado = "error"
            job.error = "Empresa o credenciales no encontradas"
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
            return

        clave_en_claro = descifrar_clave_sol(credencial.clave_cifrada, credencial.dek_cifrada)

        from adapter import generar_reporte_tributario_terceros

        token_slot = adquirir_slot_global()
        try:
            resultado = None
            for intento in range(1, MAX_INTENTOS + 1):
                resultado = generar_reporte_tributario_terceros(
                    ruc=empresa.ruc,
                    usuario_sol=credencial.usuario_sol,
                    clave_sol=clave_en_claro,
                    correo_destino=job.correo_destino,
                    razon_social=empresa.razon_social,
                    headless=False,
                    on_progreso=_reportar_etapa,
                )
                if resultado["ok"]:
                    break
                logger.warning(
                    f"Intento {intento}/{MAX_INTENTOS} fallo para {empresa.ruc}: {resultado['error']}"
                )
                # A diferencia de ejecutar_consulta_buzon, aca no se reintenta a
                # ciegas: SUNAT limita este reporte a 3 solicitudes por dia por
                # empresa, y si la falla ocurrio despues del clic en "Enviar"
                # (solicitud_pudo_haberse_enviado=True), reintentar podria gastar
                # una solicitud valida en un reenvio innecesario.
                if resultado.get("solicitud_pudo_haberse_enviado"):
                    logger.warning(
                        f"No se reintenta para {empresa.ruc}: la solicitud pudo haberse enviado ya "
                        "(cuenta contra el limite diario de SUNAT)"
                    )
                    break
                if resultado.get("verificacion_humana") or resultado.get("credenciales_rechazadas"):
                    break
                if intento < MAX_INTENTOS:
                    time.sleep(ESPERA_ENTRE_INTENTOS_SEG * intento)
        finally:
            liberar_slot_global(token_slot)

        if not resultado["ok"]:
            job.estado = "error"
            job.error = (resultado["error"] or "Error desconocido")[:1000]
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
            _reportar_etapa(None)
            logger.warning(f"ReporteTributarioJob {job_id} fallo para {empresa.ruc}: {job.error}")
            return

        job.estado = "completado"
        job.finalizado_en = datetime.now(timezone.utc)
        db.commit()
        _reportar_etapa(None)
        logger.info(f"ReporteTributarioJob {job_id} completado para {empresa.ruc} -> {job.correo_destino}")

    except Exception as e:
        logger.exception(f"Error ejecutando ReporteTributarioJob {job_id}")
        db.rollback()
        job = db.query(ReporteTributarioJob).filter(ReporteTributarioJob.id == job_id).first()
        if job:
            job.estado = "error"
            job.error = str(e)[:1000]
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
        _reportar_etapa(None)
    finally:
        db.close()


def _sire_presentado(cod_estado: str, des_estado: str) -> bool:
    des = (des_estado or "").strip().lower()
    if des:
        return des == "presentado"
    return cod_estado in ("01", "02")


def ejecutar_consulta_sire(job_id: str):
    """Lee de SUNAT el estado de presentacion de todos los periodos SIRE (RVIE y RCE) de una empresa y los guarda."""
    db = SessionLocal()

    def _reportar_etapa(etapa: str | None):
        db_etapa = SessionLocal()
        try:
            job_actual = db_etapa.query(ConsultaSireJob).filter(ConsultaSireJob.id == job_id).first()
            if job_actual:
                job_actual.etapa = etapa
                db_etapa.commit()
        finally:
            db_etapa.close()

    try:
        job = db.query(ConsultaSireJob).filter(ConsultaSireJob.id == job_id).first()
        if not job:
            logger.error(f"ConsultaSireJob {job_id} no encontrado")
            return

        job.estado = "en_progreso"
        job.iniciado_en = datetime.now(timezone.utc)
        db.commit()

        empresa = db.query(Empresa).filter(Empresa.id == job.empresa_id).first()
        credencial = (
            db.query(CredencialSol).filter(CredencialSol.empresa_id == job.empresa_id).first()
            if empresa else None
        )
        if not empresa or not credencial:
            job.estado = "error"
            job.error = "Empresa o credenciales no encontradas"
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
            return

        clave_en_claro = descifrar_clave_sol(credencial.clave_cifrada, credencial.dek_cifrada)

        from adapter import consultar_estado_sire

        token_slot = adquirir_slot_global()
        try:
            resultado = None
            for intento in range(1, MAX_INTENTOS + 1):
                resultado = consultar_estado_sire(
                    ruc=empresa.ruc,
                    usuario_sol=credencial.usuario_sol,
                    clave_sol=clave_en_claro,
                    razon_social=empresa.razon_social,
                    headless=False,
                    on_progreso=_reportar_etapa,
                )
                if resultado["ok"]:
                    break
                logger.warning(f"SIRE intento {intento}/{MAX_INTENTOS} fallo para {empresa.ruc}: {resultado['error']}")
                if resultado.get("credenciales_rechazadas"):
                    break
                if intento < MAX_INTENTOS:
                    time.sleep(ESPERA_ENTRE_INTENTOS_SEG * intento)
        finally:
            liberar_slot_global(token_slot)

        if not resultado["ok"]:
            job.estado = "error"
            job.error = (resultado["error"] or "Error desconocido")[:1000]
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
            _reportar_etapa(None)
            return

        ahora = datetime.now(timezone.utc)
        existentes = {
            (e.libro, e.periodo): e
            for e in db.query(SireEstadoPeriodo).filter(SireEstadoPeriodo.empresa_id == empresa.id)
        }
        actualizados = 0
        for libro, periodos in resultado["libros"].items():
            for p in periodos:
                fila = existentes.get((libro, p["periodo"]))
                if fila is None:
                    fila = SireEstadoPeriodo(empresa_id=empresa.id, libro=libro, periodo=p["periodo"])
                    db.add(fila)
                fila.cod_estado = p["cod_estado"][:5]
                fila.des_estado = p["des_estado"][:60]
                fila.presentado = _sire_presentado(p["cod_estado"], p["des_estado"])
                fila.actualizado_en = ahora
                actualizados += 1

        job.estado = "completado"
        job.periodos_actualizados = actualizados
        job.finalizado_en = ahora
        db.commit()
        _reportar_etapa(None)
        logger.info(f"ConsultaSireJob {job_id} completado para {empresa.ruc}: {actualizados} periodo(s)")

    except Exception as e:
        logger.exception(f"Error ejecutando ConsultaSireJob {job_id}")
        db.rollback()
        job = db.query(ConsultaSireJob).filter(ConsultaSireJob.id == job_id).first()
        if job:
            job.estado = "error"
            job.error = str(e)[:1000]
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
        _reportar_etapa(None)
    finally:
        db.close()


# Campos de ValorDeuda que se copian tal cual de lo que devuelve
# adapter.consultar_valores_pendientes (ver normalizar_valor).
_CAMPOS_VALOR_DEUDA = (
    "tipo", "tipo_descripcion", "periodo", "cod_tributo", "tributo", "estado", "etapa_cod", "etapa",
    "etapa_alterna", "en_cobranza_coactiva", "num_expediente_coactivo", "monto_tributo", "tributo_pendiente",
    "interes", "saldo_total", "saldo_exigible",
)


def _fecha_o_none(iso: str | None):
    return datetime.strptime(iso, "%Y-%m-%d").date() if iso else None


def aplicar_lectura_valores(db, empresa_id: str, valores: list[dict], ahora: datetime, avisar_nuevos: bool = True) -> dict:
    """
    Cruza una lectura COMPLETA de valores pendientes con lo ya guardado: alta
    de los nuevos, cambios de etapa/saldo al historial, y los que ya no
    vienen pasan a vigente=False (nunca se borran -- es el historial de
    deudas que pidio el usuario). Solo debe llamarse con una lectura que
    cubrio todo el rango; una parcial marcaria como desaparecidas deudas que
    siguen vigentes.

    avisar_nuevos=False en la primera lectura de la empresa: lo que ya debia
    es la linea base, no "valores nuevos" para la ventana emergente.
    """
    marca = ahora.isoformat()
    db.flush()  # que la consulta de abajo vea tambien lo agregado y aun no guardado en esta sesion
    existentes = {v.num_valor: v for v in db.query(ValorDeuda).filter(ValorDeuda.empresa_id == empresa_id)}
    vistos = set()
    nuevos = 0
    for dato in valores:
        numero = dato["num_valor"][:20]
        vistos.add(numero)
        fila = existentes.get(numero)
        eventos = []
        if fila is None:
            fila = ValorDeuda(
                empresa_id=empresa_id, num_valor=numero, detectado_en=ahora, historial=[],
                notificado_popup=not avisar_nuevos,
            )
            db.add(fila)
            eventos.append({"fecha": marca, "evento": "nuevo", "detalle": f"{dato['etapa']} -- saldo S/ {dato['saldo_total']:,.2f}"})
            nuevos += 1
        else:
            if not fila.vigente:
                eventos.append({"fecha": marca, "evento": "reaparecio", "detalle": dato["etapa"]})
                # Una deuda que habia desaparecido y vuelve (p. ej. se perdio
                # un fraccionamiento) es tan importante como una nueva.
                fila.notificado_popup = not avisar_nuevos
            if fila.etapa != dato["etapa"][:80]:
                eventos.append({"fecha": marca, "evento": "cambio_etapa", "detalle": f"{fila.etapa} -> {dato['etapa']}"})
            # Se compara el tributo SIN intereses: los intereses suben casi a
            # diario y llenarian el historial de "cambios" que no lo son.
            if round(fila.tributo_pendiente or 0, 2) != round(dato["tributo_pendiente"], 2):
                eventos.append({
                    "fecha": marca, "evento": "cambio_saldo",
                    "detalle": (
                        f"tributo pendiente S/ {fila.tributo_pendiente or 0:,.2f} -> S/ {dato['tributo_pendiente']:,.2f} "
                        f"(saldo con intereses S/ {dato['saldo_total']:,.2f})"
                    ),
                })
        for campo in _CAMPOS_VALOR_DEUDA:
            setattr(fila, campo, dato[campo])
        fila.tipo = (fila.tipo or "")[:10]
        fila.tipo_descripcion = (fila.tipo_descripcion or "")[:80]
        fila.tributo = (fila.tributo or "")[:150]
        fila.etapa = (fila.etapa or "")[:80]
        fila.etapa_alterna = (fila.etapa_alterna or "")[:80]
        fila.estado = (fila.estado or "")[:60]
        fila.fecha_emision = _fecha_o_none(dato.get("fecha_emision"))
        fila.fecha_notificacion = _fecha_o_none(dato.get("fecha_notificacion"))
        fila.vigente = True
        fila.visto_en = ahora
        fila.ya_no_aparece_desde = None
        if eventos:
            # Se reasigna (no .append) para que SQLAlchemy detecte el cambio en la columna JSON.
            fila.historial = list(fila.historial or []) + eventos

    for numero, fila in existentes.items():
        if numero not in vistos and fila.vigente:
            fila.vigente = False
            fila.ya_no_aparece_desde = ahora
            fila.historial = list(fila.historial or []) + [{
                "fecha": marca, "evento": "ya_no_aparece",
                "detalle": f"ultimo saldo S/ {fila.saldo_total or 0:,.2f}",
            }]
    return {"vigentes": len(vistos), "nuevos": nuevos}


def ejecutar_consulta_deudas(job_id: str):
    """Lee de SUNAT los valores pendientes de pago (2020 -> mes pasado) de una empresa y actualiza su historial de deudas."""
    db = SessionLocal()

    def _reportar_etapa(etapa: str | None):
        db_etapa = SessionLocal()
        try:
            job_actual = db_etapa.query(ConsultaDeudasJob).filter(ConsultaDeudasJob.id == job_id).first()
            if job_actual:
                job_actual.etapa = etapa
                db_etapa.commit()
        finally:
            db_etapa.close()

    try:
        job = db.query(ConsultaDeudasJob).filter(ConsultaDeudasJob.id == job_id).first()
        if not job:
            logger.error(f"ConsultaDeudasJob {job_id} no encontrado")
            return

        job.estado = "en_progreso"
        job.iniciado_en = datetime.now(timezone.utc)
        db.commit()

        empresa = db.query(Empresa).filter(Empresa.id == job.empresa_id).first()
        credencial = (
            db.query(CredencialSol).filter(CredencialSol.empresa_id == job.empresa_id).first()
            if empresa else None
        )
        if not empresa or not credencial:
            job.estado = "error"
            job.error = "Empresa o credenciales no encontradas"
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
            return

        clave_en_claro = descifrar_clave_sol(credencial.clave_cifrada, credencial.dek_cifrada)

        from adapter import consultar_valores_pendientes

        token_slot = adquirir_slot_global()
        try:
            resultado = None
            for intento in range(1, MAX_INTENTOS + 1):
                resultado = consultar_valores_pendientes(
                    ruc=empresa.ruc,
                    usuario_sol=credencial.usuario_sol,
                    clave_sol=clave_en_claro,
                    razon_social=empresa.razon_social,
                    headless=False,
                    on_progreso=_reportar_etapa,
                )
                if resultado["ok"]:
                    break
                logger.warning(f"Deudas intento {intento}/{MAX_INTENTOS} fallo para {empresa.ruc}: {resultado['error']}")
                if resultado.get("credenciales_rechazadas"):
                    break
                if intento < MAX_INTENTOS:
                    time.sleep(ESPERA_ENTRE_INTENTOS_SEG * intento)
        finally:
            liberar_slot_global(token_slot)

        if not resultado["ok"]:
            job.estado = "error"
            job.error = (resultado["error"] or "Error desconocido")[:1000]
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
            _reportar_etapa(None)
            return

        ahora = datetime.now(timezone.utc)
        ya_tenia_lectura = (
            db.query(ConsultaDeudasJob.id)
            .filter(
                ConsultaDeudasJob.empresa_id == empresa.id,
                ConsultaDeudasJob.estado == "completado",
                ConsultaDeudasJob.id != job.id,
            )
            .first()
        ) is not None
        cuenta = aplicar_lectura_valores(db, empresa.id, resultado["valores"], ahora, avisar_nuevos=ya_tenia_lectura)
        job.estado = "completado"
        job.valores_vigentes = cuenta["vigentes"]
        job.valores_nuevos = cuenta["nuevos"]
        job.finalizado_en = ahora
        db.commit()
        _reportar_etapa(None)
        logger.info(
            f"ConsultaDeudasJob {job_id} completado para {empresa.ruc}: "
            f"{cuenta['vigentes']} vigente(s), {cuenta['nuevos']} nuevo(s)"
        )

    except Exception as e:
        logger.exception(f"Error ejecutando ConsultaDeudasJob {job_id}")
        db.rollback()
        job = db.query(ConsultaDeudasJob).filter(ConsultaDeudasJob.id == job_id).first()
        if job:
            job.estado = "error"
            job.error = str(e)[:1000]
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
        _reportar_etapa(None)
    finally:
        db.close()
