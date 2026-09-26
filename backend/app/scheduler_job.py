"""
Logica del chequeo nocturno (Fase 2, semana 8 del roadmap): recorrer todas
las empresas activas, encolar sus consultas al buzon espaciadas en el
tiempo, y despues enviar un correo de resumen por tenant con lo que salio
nuevo.

Separado en dos pasos independientes (encolar / avisar) en vez de uno solo
que espere a que todo termine, porque una consulta real a SUNAT puede tardar
uno o dos minutos y con decenas de empresas la espera total seria larga --
mas simple dejar que el scheduler dispare el aviso un rato despues (ver
scheduler_entry.py) que mantener vivo un proceso esperando.

Estas mismas dos funciones las llama tanto el proceso de scheduler (cron
diario) como los endpoints /admin (para poder probarlas manualmente sin
esperar al horario programado).
"""
import os
import time
import logging
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import Empresa, Tenant, CredencialSol, ConsultaJob, CanarioCheck
from app.models import Usuario
from app.queue_conn import cola_consultas, redis_conn
from app.jobs import ejecutar_consulta_buzon
from app.email_utils import enviar_resumen_diario, enviar_alerta_canario
from app.rate_limit import adquirir_slot_global, liberar_slot_global, espaciado_consultas_seg
from app.security import descifrar_clave_sol

logger = logging.getLogger("app.scheduler_job")

# Fase 3 (confiabilidad/observabilidad): correo que recibe la alerta del
# canario -- es un aviso operativo para quien administra el sistema, no
# para un tenant en particular, asi que no sale de la tabla de usuarios
# (que son cuentas de clientes) sino de esta variable de entorno.
ALERTA_CANARIO_EMAIL = os.environ.get("ALERTA_CANARIO_EMAIL", "brianconhuay@gmail.com")

# Cuantos chequeos canario seguidos tienen que fallar antes de mandar la
# alerta -- mas de 1 para no disparar un correo por un fallo suelto
# (timeout de red, SUNAT lento un momento), pero lo bastante bajo para
# enterarse rapido de un problema real.
CANARIO_FALLOS_CONSECUTIVOS_PARA_ALERTA = int(
    os.environ.get("CANARIO_FALLOS_CONSECUTIVOS_PARA_ALERTA", 2)
)

_CLAVE_REDIS_CANARIO_EN_ALERTA = "canario:en_alerta"


def encolar_chequeo_nocturno(espaciado_seg: int | None = None) -> dict:
    """
    Crea un ConsultaJob 'pendiente' por cada empresa activa (de un tenant
    activo, con credenciales cargadas) y lo programa en la cola con
    enqueue_in() para que se ejecute mas adelante -- la primera ya mismo, la
    segunda espaciado_seg despues, la tercera 2*espaciado_seg despues, etc.
    Usar enqueue_in() en vez de un time.sleep() en este mismo proceso deja
    que esta funcion (y el endpoint /admin que la llama) responda al toque,
    sin importar cuantas empresas haya.

    espaciado_seg=None (default) usa el valor configurado en el panel
    maestro (Fase 5, ver app.rate_limit.espaciado_consultas_seg) -- se
    resuelve aca y no como default del parametro porque ese se evalua una
    sola vez al importar el modulo, no en cada llamada.

    Requiere que el worker corra con with_scheduler=True (ver worker_entry.py)
    para que los jobs programados realmente se muevan a la cola cuando les
    toca.
    """
    if espaciado_seg is None:
        espaciado_seg = espaciado_consultas_seg()
    db = SessionLocal()
    try:
        empresas = (
            db.query(Empresa)
            .join(Tenant, Tenant.id == Empresa.tenant_id)
            .filter(Empresa.activo.is_(True), Tenant.activo.is_(True))
            .order_by(Empresa.ultima_consulta_en.asc().nulls_first())
            .all()
        )

        encolados = 0
        saltados_sin_credencial = 0
        for empresa in empresas:
            tiene_credencial = (
                db.query(CredencialSol.id).filter(CredencialSol.empresa_id == empresa.id).first()
            )
            if not tiene_credencial:
                saltados_sin_credencial += 1
                logger.warning(f"Empresa {empresa.ruc} sin credenciales SOL, se salta del chequeo nocturno")
                continue

            job = ConsultaJob(empresa_id=empresa.id, solicitado_por=None, estado="pendiente", origen="masiva")
            db.add(job)
            db.commit()
            db.refresh(job)

            cola_consultas.enqueue_in(
                timedelta(seconds=encolados * espaciado_seg),
                ejecutar_consulta_buzon,
                job.id,
                job_timeout="10m",
            )
            encolados += 1

        logger.info(
            f"Chequeo nocturno: {encolados} empresa(s) encoladas (espaciadas {espaciado_seg}s), "
            f"{saltados_sin_credencial} salteada(s) por falta de credenciales"
        )
        return {
            "empresas_encoladas": encolados,
            "saltadas_sin_credencial": saltados_sin_credencial,
            "espaciado_seg": espaciado_seg,
        }
    finally:
        db.close()


def enviar_resumenes_diarios(horas_atras: int = 12) -> dict:
    """
    Busca los ConsultaJob completados con mensajes nuevos en las ultimas
    `horas_atras` horas que todavia no se incluyeron en ningun correo
    (notificado=False), los agrupa por tenant, y le manda un correo de
    resumen a cada usuario de ese tenant. Marca esos jobs como notificados
    para no repetir el aviso si esto se vuelve a correr (p.ej. durante
    pruebas manuales).
    """
    db = SessionLocal()
    try:
        desde = datetime.now(timezone.utc) - timedelta(hours=horas_atras)
        jobs_pendientes = (
            db.query(ConsultaJob)
            .filter(
                ConsultaJob.estado == "completado",
                ConsultaJob.mensajes_nuevos > 0,
                ConsultaJob.notificado.is_(False),
                ConsultaJob.finalizado_en.isnot(None),
                ConsultaJob.finalizado_en >= desde,
            )
            .all()
        )

        por_tenant: dict[str, list[tuple[ConsultaJob, Empresa]]] = {}
        for job in jobs_pendientes:
            empresa = db.query(Empresa).filter(Empresa.id == job.empresa_id).first()
            if not empresa:
                continue
            por_tenant.setdefault(empresa.tenant_id, []).append((job, empresa))

        correos_enviados = 0
        for tenant_id, pares in por_tenant.items():
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if not tenant:
                continue
            usuarios_tenant = db.query(Usuario).filter(Usuario.tenant_id == tenant_id).all()
            resumen = [
                {
                    "ruc": empresa.ruc,
                    "razon_social": empresa.razon_social,
                    "mensajes_nuevos": job.mensajes_nuevos,
                }
                for job, empresa in pares
            ]
            for usuario in usuarios_tenant:
                enviar_resumen_diario(usuario.email, tenant.nombre, resumen)
                correos_enviados += 1

            for job, _ in pares:
                job.notificado = True

        db.commit()
        logger.info(
            f"Resumen diario: {len(por_tenant)} tenant(s) con novedades, {correos_enviados} correo(s) enviado(s)"
        )
        return {"tenants_notificados": len(por_tenant), "correos_enviados": correos_enviados}
    finally:
        db.close()


def ejecutar_chequeo_canario() -> dict:
    """
    Fase 3 (confiabilidad/observabilidad): corre un login de prueba contra
    cada empresa marcada como es_canario=True -- SEPARADO por completo de
    las consultas normales de los tenants (no crea ConsultaJob, no guarda
    mensajes, no toca los datos de la empresa) para que este chequeo nunca
    interfiera con lo que ve un cliente en su tablero. Solo mide: ¿el login
    a SUNAT sigue funcionando?, ¿cuanto tarda?, ¿que "flujo" post-login
    mostro SUNAT esta vez? -- y lo guarda en CanarioCheck.

    Si no hay ninguna empresa marcada como canario, no hace nada (esto es
    valido -- el chequeo canario es opcional, hay que marcar una empresa a
    proposito para activarlo).

    IMPORTANTE (bug real detectado en produccion el 18/09): esta funcion
    abre una sesion real de Selenium/Chrome con headless=False, igual que
    una consulta normal -- necesita una pantalla virtual (Xvfb) montada,
    porque SUNAT corta la conexion si detecta Chrome headless de verdad.
    El `worker` ya arranca la suya en worker_entry.py, pero esta funcion
    TAMBIEN se llama desde `scheduler` (chequeo periodico) y desde
    `backend` (endpoint POST /admin/canario/ejecutar) -- ninguno de esos
    dos procesos arranca una pantalla por su cuenta. Sin esto, el canario
    fallaba con "No se pudo iniciar el navegador" en TODOS los casos (no
    tiene nada que ver con un cambio de SUNAT) -- mismo patron ya usado en
    los scripts de diagnostico standalone (ver diagnostico_ficha_ruc.py).
    """
    db = SessionLocal()
    try:
        empresas_canario = db.query(Empresa).filter(Empresa.es_canario.is_(True)).all()
        if not empresas_canario:
            logger.info("Chequeo canario: ninguna empresa marcada como es_canario, se salta.")
            return {"chequeos_ejecutados": 0, "motivo": "sin_empresa_canario"}

        from adapter import consultar_buzon

        # Si ya hay un DISPLAY activo (p.ej. esta funcion corriendo dentro
        # del worker, que arranca el suyo en worker_entry.py) no arrancamos
        # una segunda de encima -- solo cuando falta (scheduler / backend).
        display = None
        if not os.environ.get("DISPLAY"):
            from pyvirtualdisplay import Display
            display = Display(visible=False, size=(1600, 1000))
            display.start()
            logger.info(
                f"Chequeo canario: pantalla virtual (Xvfb) propia arrancada en DISPLAY={os.environ.get('DISPLAY')}"
            )

        try:
            resultados = []
            for empresa in empresas_canario:
                credencial = db.query(CredencialSol).filter(CredencialSol.empresa_id == empresa.id).first()
                if not credencial:
                    logger.warning(f"Chequeo canario: {empresa.ruc} no tiene credenciales SOL, se salta.")
                    continue

                clave_en_claro = descifrar_clave_sol(credencial.clave_cifrada, credencial.dek_cifrada)

                inicio = time.time()
                adquirir_slot_global()
                try:
                    resultado = consultar_buzon(
                        ruc=empresa.ruc,
                        usuario_sol=credencial.usuario_sol,
                        clave_sol=clave_en_claro,
                        razon_social=empresa.razon_social,
                        headless=False,
                        descargar_documentos=False,  # el canario no necesita PDFs, solo medir el login
                        leer_buzon_mensajes=False,  # idem -- solo medir el login, no leer Buzón Mensajes
                    )
                finally:
                    liberar_slot_global()
                duracion_seg = round(time.time() - inicio, 2)

                check = CanarioCheck(
                    empresa_id=empresa.id,
                    exito=resultado["ok"],
                    duracion_seg=duracion_seg,
                    flujo_detectado=resultado.get("flujo_detectado"),
                    error=(resultado.get("error") or None),
                )
                db.add(check)
                db.commit()

                logger.info(
                    f"Chequeo canario para {empresa.ruc}: exito={resultado['ok']}, "
                    f"duracion={duracion_seg}s, flujo={check.flujo_detectado}"
                    + (f", error={check.error}" if check.error else "")
                )
                resultados.append({
                    "ruc": empresa.ruc,
                    "exito": resultado["ok"],
                    "duracion_seg": duracion_seg,
                    "flujo_detectado": check.flujo_detectado,
                })

            _evaluar_alerta_canario(db)
            return {"chequeos_ejecutados": len(resultados), "resultados": resultados}
        finally:
            if display is not None:
                display.stop()
    finally:
        db.close()


def _evaluar_alerta_canario(db) -> None:
    """
    Revisa los ultimos CANARIO_FALLOS_CONSECUTIVOS_PARA_ALERTA chequeos
    canario (de todas las empresas canario juntas, mas reciente primero):
    si TODOS fallaron y todavia no se aviso de este problema, manda el
    correo de alerta. Si el mas reciente fue exitoso y habia una alerta
    activa, manda el correo de "se recupero" y limpia el estado.

    Usa una bandera en Redis (no una tabla nueva) para no repetir el mismo
    aviso una y otra vez mientras el problema sigue activo -- mismo estilo
    que el resto del rate limiting del sistema (ver rate_limit.py).
    """
    ultimos = (
        db.query(CanarioCheck)
        .order_by(CanarioCheck.ejecutado_en.desc())
        .limit(CANARIO_FALLOS_CONSECUTIVOS_PARA_ALERTA)
        .all()
    )
    if len(ultimos) < CANARIO_FALLOS_CONSECUTIVOS_PARA_ALERTA:
        return  # no hay suficiente historial todavia para decidir nada

    todos_fallaron = all(not c.exito for c in ultimos)
    ya_en_alerta = redis_conn.get(_CLAVE_REDIS_CANARIO_EN_ALERTA) is not None

    if todos_fallaron and not ya_en_alerta:
        redis_conn.set(_CLAVE_REDIS_CANARIO_EN_ALERTA, "1")
        detalle = [
            f"{c.ejecutado_en.strftime('%d/%m %H:%M') if c.ejecutado_en else '?'} -- "
            f"{c.error or 'error desconocido'}"
            for c in ultimos
        ]
        enviar_alerta_canario(ALERTA_CANARIO_EMAIL, detalle, recuperado=False)
        logger.warning(
            f"ALERTA CANARIO: {CANARIO_FALLOS_CONSECUTIVOS_PARA_ALERTA} fallo(s) seguido(s), "
            f"correo enviado a {ALERTA_CANARIO_EMAIL}"
        )
    elif not todos_fallaron and ya_en_alerta:
        redis_conn.delete(_CLAVE_REDIS_CANARIO_EN_ALERTA)
        enviar_alerta_canario(ALERTA_CANARIO_EMAIL, [], recuperado=True)
        logger.info("El canario se recupero -- estado de alerta limpiado y correo de recuperacion enviado.")
