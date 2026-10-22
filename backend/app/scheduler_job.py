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
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func

from app.database import SessionLocal
from app.models import Empresa, Tenant, CredencialSol, ConsultaJob, CanarioCheck, TareaObligacion
from app.models import Usuario, ConsultaDeudasJob, ConsultaSireJob, ConsultaDeclaracionesJob, CronogramaVencimiento
from app.models import ConsultaDetraccionesJob, DetraccionCobertura, DetraccionPago
from app.queue_conn import cola_consultas, redis_conn
from app.jobs import (
    ejecutar_consulta_buzon, ejecutar_consulta_deudas, ejecutar_consulta_sire, ejecutar_consulta_declaraciones,
    ejecutar_consulta_detracciones,
)
from app.cumplimiento import empresas_de_tenants_activos, encolar_lecturas, filtrar_activas_en_sunat
from app.cronograma_sunat import grupo_para_empresa
from app.email_utils import enviar_resumen_diario, enviar_alerta_canario, enviar_recordatorio_tareas
from app.rate_limit import adquirir_slot_global, liberar_slot_global, espaciado_consultas_seg
from app.security import descifrar_clave_sol
from app.hora_peru import ZONA_PERU, etiqueta_de_hoy, hoy_peru

# Modulo de Tareas/Agenda: con cuantos dias de anticipacion se manda el
# recordatorio por correo de una tarea pendiente -- ver
# enviar_recordatorios_vencimiento.
DIAS_RECORDATORIO_TAREAS = int(os.environ.get("DIAS_RECORDATORIO_TAREAS", 3))

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


def encolar_deudas_diario() -> dict:
    """Modulo Cumplimiento > Deudas: relee cada dia los valores pendientes de todas las empresas activas en SUNAT."""
    db = SessionLocal()
    try:
        empresas = filtrar_activas_en_sunat(empresas_de_tenants_activos(db)).order_by(Empresa.razon_social).all()
        resultado = encolar_lecturas(db, empresas, ConsultaDeudasJob, ejecutar_consulta_deudas)
        logger.info(f"Lectura diaria de deudas: {resultado}")
        return resultado
    finally:
        db.close()


# SIRE y Declaracion mensual: se relee una empresa si su ultima lectura buena
# tiene mas de estos dias, o si ayer/anteayer vencio su plazo del cronograma
# que corresponde (asi el cuadro refleja enseguida quien presento a tiempo y
# quien no) -- sin gastar un ingreso a SUNAT diario por empresa.
DIAS_REFRESCO_SIRE = int(os.environ.get("DIAS_REFRESCO_SIRE", 7))
_DIAS_TRAS_VENCIMIENTO = 2
_ZONA_LIMA = timezone(timedelta(hours=-5))


def empresas_para_refresco(db, modelo_job, tipo_cronograma: str, hoy=None) -> list[Empresa]:
    hoy = hoy or datetime.now(_ZONA_LIMA).date()
    empresas = filtrar_activas_en_sunat(empresas_de_tenants_activos(db)).order_by(Empresa.razon_social).all()
    ultima_lectura = dict(
        db.query(modelo_job.empresa_id, func.max(modelo_job.finalizado_en))
        .filter(modelo_job.estado == "completado")
        .group_by(modelo_job.empresa_id)
        .all()
    )
    vencimientos_recientes: dict[str, list] = {}
    for grupo, fecha in db.query(CronogramaVencimiento.grupo, CronogramaVencimiento.fecha_vencimiento).filter(
        CronogramaVencimiento.tipo == tipo_cronograma,
        CronogramaVencimiento.fecha_vencimiento >= datetime.combine(
            hoy - timedelta(days=_DIAS_TRAS_VENCIMIENTO), datetime.min.time(), tzinfo=timezone.utc
        ),
        CronogramaVencimiento.fecha_vencimiento < datetime.combine(hoy, datetime.min.time(), tzinfo=timezone.utc),
    ):
        vencimientos_recientes.setdefault(grupo, []).append(fecha.date())

    elegidas = []
    for empresa in empresas:
        leida = ultima_lectura.get(empresa.id)
        if leida is not None and leida.tzinfo is None:
            leida = leida.replace(tzinfo=timezone.utc)
        leida_dia = leida.astimezone(_ZONA_LIMA).date() if leida else None
        if leida_dia is None or (hoy - leida_dia).days >= DIAS_REFRESCO_SIRE:
            elegidas.append(empresa)
            continue
        grupo = grupo_para_empresa(empresa.ruc, empresa.es_buen_contribuyente)
        if any(leida_dia <= vence for vence in vencimientos_recientes.get(grupo, [])):
            elegidas.append(empresa)
    return elegidas


def empresas_para_refresco_sire(db, hoy=None) -> list[Empresa]:
    return empresas_para_refresco(db, ConsultaSireJob, "sire", hoy)


def encolar_sire_programado() -> dict:
    """Modulo Cumplimiento > SIRE: lectura diaria SOLO de las empresas que lo necesitan (ver empresas_para_refresco)."""
    db = SessionLocal()
    try:
        resultado = encolar_lecturas(db, empresas_para_refresco_sire(db), ConsultaSireJob, ejecutar_consulta_sire)
        logger.info(f"Lectura programada del SIRE: {resultado}")
        return resultado
    finally:
        db.close()


def encolar_declaraciones_programado() -> dict:
    """Modulo Cumplimiento > Declaracion mensual: igual que el SIRE, pero con el cronograma mensual."""
    db = SessionLocal()
    try:
        empresas = empresas_para_refresco(db, ConsultaDeclaracionesJob, "mensual")
        resultado = encolar_lecturas(db, empresas, ConsultaDeclaracionesJob, ejecutar_consulta_declaraciones)
        logger.info(f"Lectura programada de declaraciones: {resultado}")
        return resultado
    finally:
        db.close()


# Detracciones: el historial se arma por FECHA DE PAGO, no por periodo -- un
# deposito pagado hoy de una factura de 05/2025 entra en la lectura de esta
# semana y se guarda con su periodo real (buscando por periodo se perderia).
# 1) Carga inicial, una sola vez por empresa: desde el 01/01/2022 (lo anterior
#    ya prescribio) hasta hoy, unas pocas empresas por noche; retoma donde quedo.
# 2) Semanal: solo lo nuevo desde la marca de avance, repasando 7 dias por lo
#    que SUNAT registra tarde. Las cuentas IVAP / Ley 30737 y las empresas sin
#    ningun deposito se revisan solo la primera semana de cada mes.
# La carga inicial lee solo pagos individuales: los "pagos masivos" de
# periodos antiguos tardan 50-60 s por consulta en SUNAT (medido 22/10/2026;
# alguna se colgo mas de 2 min), y los recientes responden al instante, asi que
# esos se toman desde las lecturas semanales (o con "Buscar en SUNAT").
INICIO_HISTORIAL_DETRACCIONES = date(2022, 1, 1)
DETRACCIONES_CARGA_POR_NOCHE = int(os.environ.get("DETRACCIONES_CARGA_POR_NOCHE", 20))
DIAS_REPASO_DETRACCIONES = 7
DIAS_REPASO_MENSUAL_DETRACCIONES = 42
TIPOS_PAGO_AUTOMATICOS = "pagosIndividuales,pagosMasivos"


def _empresas_activas_con_clave(db) -> list[Empresa]:
    con_clave = {eid for (eid,) in db.query(CredencialSol.empresa_id)}
    return [
        e for e in filtrar_activas_en_sunat(empresas_de_tenants_activos(db)).order_by(Empresa.razon_social).all()
        if e.id in con_clave
    ]


def encolar_detracciones_carga_inicial() -> dict:
    """Cada noche: el historial desde 2022 de las empresas que todavia no lo tienen completo."""
    db = SessionLocal()
    try:
        hoy = hoy_peru()
        completas = {
            eid for (eid,) in db.query(DetraccionCobertura.empresa_id).filter(DetraccionCobertura.carga_completa.is_(True))
        }
        pendientes = [e for e in _empresas_activas_con_clave(db) if e.id not in completas][:DETRACCIONES_CARGA_POR_NOCHE]
        resultado = encolar_lecturas(
            db, pendientes, ConsultaDetraccionesJob, ejecutar_consulta_detracciones,
            datos_job={
                "modo": "carga_inicial",
                "fecha_desde": INICIO_HISTORIAL_DETRACCIONES,
                "fecha_hasta": hoy,
                "tipos_cuenta": "1,2,3",
                "tipos_pago": "pagosIndividuales",
            },
            job_timeout="40m",
        )
        logger.info(f"Carga inicial de detracciones: {resultado}")
        return resultado
    finally:
        db.close()


def encolar_detracciones_semanal() -> dict:
    """Cada semana: lo nuevo desde la marca de avance de cada empresa con la carga inicial terminada."""
    db = SessionLocal()
    try:
        hoy = hoy_peru()
        revision_mensual = hoy.day <= 7
        coberturas = {
            c.empresa_id: c
            for c in db.query(DetraccionCobertura).filter(DetraccionCobertura.carga_completa.is_(True))
        }
        cuentas_usadas: dict[str, set[str]] = {}
        for eid, cuenta in db.query(DetraccionPago.empresa_id, DetraccionPago.tipo_cuenta).distinct():
            cuentas_usadas.setdefault(eid, set()).add(cuenta)
        empresas = [
            e for e in _empresas_activas_con_clave(db)
            if e.id in coberturas and (e.id in cuentas_usadas or revision_mensual)
        ]

        def criterios(empresa):
            hasta = coberturas[empresa.id].hasta
            if revision_mensual:
                cuentas, repaso = {"1", "2", "3"}, DIAS_REPASO_MENSUAL_DETRACCIONES
            else:
                cuentas, repaso = cuentas_usadas[empresa.id] | {"1"}, DIAS_REPASO_DETRACCIONES
            return {
                "modo": "semanal",
                "fecha_desde": min(hasta - timedelta(days=repaso), hoy),
                "fecha_hasta": hoy,
                "tipos_cuenta": ",".join(sorted(cuentas)),
                "tipos_pago": TIPOS_PAGO_AUTOMATICOS,
            }

        resultado = encolar_lecturas(
            db, empresas, ConsultaDetraccionesJob, ejecutar_consulta_detracciones, datos_job=criterios, job_timeout="20m",
        )
        logger.info(f"Lectura semanal de detracciones: {resultado}")
        return resultado
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


def enviar_recordatorios_vencimiento(dias_antes: int = DIAS_RECORDATORIO_TAREAS) -> dict:
    """
    Modulo de Tareas/Agenda: recordatorio por correo de las tareas
    pendientes que vencen dentro de `dias_antes` dias -- se manda UNA sola
    vez por tarea (se marca TareaObligacion.recordatorio_enviado_en apenas
    se manda, asi que corre esto todos los dias no reenvia el mismo aviso
    mientras la tarea siga pendiente dentro de la ventana). Si alguien
    aplaza la tarea mas alla de la ventana y despues vuelve a entrar en
    ella, se vuelve a avisar (recordatorio_enviado_en no se toca al
    aplazar, pero el filtro de fecha de abajo la vuelve a encontrar solo si
    sigue sin recordatorio_enviado_en -- en la practica, una vez avisada no
    se vuelve a avisar aunque se aplace, a proposito: evita mandar un
    correo nuevo cada vez que alguien mueve la fecha).

    Se agrupa por tenant (mismo criterio que enviar_resumenes_diarios): un
    solo correo por tenant con todas las tareas, a cada usuario del tenant.
    """
    db = SessionLocal()
    try:
        # Desde HOY en Peru (las fechas de vencimiento son el dia, a las 00:00
        # UTC): con el instante actual, una tarea que vence hoy ya no avisaba.
        ahora = etiqueta_de_hoy()
        limite = ahora + timedelta(days=dias_antes)

        tareas_por_avisar = (
            db.query(TareaObligacion, Empresa)
            .join(Empresa, Empresa.id == TareaObligacion.empresa_id)
            .filter(
                TareaObligacion.estado == "pendiente",
                TareaObligacion.fecha_vencimiento.isnot(None),
                TareaObligacion.fecha_vencimiento >= ahora,
                TareaObligacion.fecha_vencimiento <= limite,
                TareaObligacion.recordatorio_enviado_en.is_(None),
                Empresa.activo.is_(True),
            )
            .all()
        )

        por_tenant: dict[str, list[tuple[TareaObligacion, Empresa]]] = {}
        for tarea, empresa in tareas_por_avisar:
            por_tenant.setdefault(empresa.tenant_id, []).append((tarea, empresa))

        correos_enviados = 0
        for tenant_id, pares in por_tenant.items():
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if not tenant:
                continue
            usuarios_tenant = db.query(Usuario).filter(Usuario.tenant_id == tenant_id).all()
            tareas_resumen = [
                {
                    "titulo": tarea.titulo,
                    "empresa_ruc": empresa.ruc,
                    "empresa_razon_social": empresa.razon_social,
                    "fecha_vencimiento": tarea.fecha_vencimiento,
                }
                for tarea, empresa in pares
            ]
            for usuario in usuarios_tenant:
                enviar_recordatorio_tareas(usuario.email, tenant.nombre, tareas_resumen, dias_antes)
                correos_enviados += 1

            for tarea, _ in pares:
                tarea.recordatorio_enviado_en = ahora

        db.commit()
        logger.info(
            f"Recordatorio de tareas: {len(por_tenant)} tenant(s) con tareas por vencer, "
            f"{len(tareas_por_avisar)} tarea(s), {correos_enviados} correo(s) enviado(s)"
        )
        return {
            "tenants_notificados": len(por_tenant),
            "tareas_avisadas": len(tareas_por_avisar),
            "correos_enviados": correos_enviados,
        }
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
                token_slot = adquirir_slot_global()
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
                    liberar_slot_global(token_slot)
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
            f"{c.ejecutado_en.astimezone(ZONA_PERU).strftime('%d/%m %H:%M') if c.ejecutado_en else '?'} -- "
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
