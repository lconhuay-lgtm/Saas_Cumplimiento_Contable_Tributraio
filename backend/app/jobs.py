"""
Funcion que RQ ejecuta para consultar el buzon de una empresa y guardar los
mensajes nuevos en la base de datos.
"""
import hashlib
import logging
import re
import time
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import ConsultaJob, FichaRucJob, Empresa, CredencialSol, MensajeBuzon
from app.security import descifrar_clave_sol
from app.rate_limit import adquirir_slot_global, liberar_slot_global
from app.almacenamiento import guardar_documento, guardar_documento_bytes, AlmacenamientoError
from app.clasificacion import clasificar_tipo

MAX_INTENTOS = 2
ESPERA_ENTRE_INTENTOS_SEG = 15

logger = logging.getLogger("app.jobs")


def _mensaje_id(fecha: str, asunto: str) -> str:
    return hashlib.sha256(f"{fecha}|{asunto}".encode("utf-8")).hexdigest()


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

        adquirir_slot_global()
        try:
            resultado = None
            for intento in range(1, MAX_INTENTOS + 1):
                resultado = consultar_buzon(
                    ruc=empresa.ruc,
                    usuario_sol=credencial.usuario_sol,
                    clave_sol=clave_en_claro,
                    razon_social=empresa.razon_social,
                    headless=False,
                    ids_conocidos=ids_conocidos,
                    on_progreso=_reportar_etapa,
                )
                if resultado["ok"]:
                    break
                logger.warning(
                    f"Intento {intento}/{MAX_INTENTOS} fallo para {empresa.ruc}: {resultado['error']}"
                )
                if intento < MAX_INTENTOS:
                    time.sleep(ESPERA_ENTRE_INTENTOS_SEG * intento)
        finally:
            liberar_slot_global()

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

        if not resultado["ok"]:
            job.estado = "error"
            job.error = (resultado["error"] or "Error desconocido")[:1000]
            job.finalizado_en = datetime.now(timezone.utc)
            db.commit()
            _reportar_etapa(None)
            logger.warning(f"Job {job_id} fallo para {empresa.ruc}: {job.error}")
            return

        nuevos = 0
        documentos_descargados = resultado.get("documentos", {}) or {}
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
                continue

            documento_ref = None
            ruta_local_pdf = documentos_descargados.get(mid)
            if ruta_local_pdf:
                try:
                    documento_ref = guardar_documento(ruta_local_pdf, empresa.id, mid)
                except AlmacenamientoError as e:
                    logger.error(f"No se pudo guardar el documento del mensaje '{msg['asunto']}': {e}")

            db.add(MensajeBuzon(
                empresa_id=empresa.id,
                mensaje_externo_id=mid,
                fecha_publicacion=_parsear_fecha(msg["fecha"]),
                asunto=msg["asunto"],
                tipo=clasificar_tipo(msg["asunto"]),
                documento_ref=documento_ref,
            ))
            nuevos += 1

        empresa.ultima_consulta_en = datetime.now(timezone.utc)
        job.estado = "completado"
        job.mensajes_nuevos = nuevos
        job.finalizado_en = datetime.now(timezone.utc)
        db.commit()
        _reportar_etapa(None)
        logger.info(f"Job {job_id} completado: {nuevos} mensajes nuevos para {empresa.ruc}")

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

        adquirir_slot_global()
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
            liberar_slot_global()

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
