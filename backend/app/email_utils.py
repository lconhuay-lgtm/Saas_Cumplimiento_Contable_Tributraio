"""
Envio del correo de resumen diario ("estas empresas tienen mensajes
nuevos"). Tiene dos modos, elegidos automaticamente segun si hay
credenciales SMTP configuradas:

- MODO PRUEBA (sin SMTP_HOST en el entorno): en vez de enviar un correo de
  verdad, se escribe el contenido a un archivo de texto dentro de
  /data/sunat/emails_dev (carpeta montada en el host, ver docker-compose.yml
  -- el usuario puede abrir el archivo directo desde Windows). Pensado para
  poder probar toda la logica de "quien deberia recibir que" sin necesitar
  una cuenta de correo real todavia.
- MODO REAL (con SMTP_HOST configurado): envia por SMTP con STARTTLS. Sirve
  para Gmail (con contrasena de aplicacion), SendGrid, o cualquier SMTP
  estandar -- basta con llenar las variables SMTP_* en el .env.
"""
import os
import smtplib
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("app.email_utils")

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "no-responder@buzonsaas.local")

DEV_MAIL_DIR = os.environ.get("SUNAT_EMAIL_DEV_DIR", "/data/sunat/emails_dev")


def _modo_prueba_activo() -> bool:
    return not SMTP_HOST


def _armar_cuerpo(nombre_tenant: str, resumen: list[dict]) -> tuple[str, str]:
    """Devuelve (asunto, cuerpo_texto_plano)."""
    total_mensajes = sum(item["mensajes_nuevos"] for item in resumen)
    asunto = f"Anzen Sol -- {total_mensajes} mensaje(s) nuevo(s) en {len(resumen)} empresa(s)"

    lineas = [
        f"Resumen diario de Anzen Sol para {nombre_tenant}",
        f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "",
        "Empresas con mensajes nuevos desde el ultimo chequeo:",
        "",
    ]
    for item in resumen:
        lineas.append(
            f"  - {item['ruc']} ({item['razon_social']}): {item['mensajes_nuevos']} mensaje(s) nuevo(s)"
        )
    lineas.append("")
    lineas.append("Ingresa al tablero para ver el detalle de cada mensaje.")
    return asunto, "\n".join(lineas)


def enviar_resumen_diario(destinatario: str, nombre_tenant: str, resumen: list[dict]) -> None:
    """
    resumen: lista de {"ruc": str, "razon_social": str, "mensajes_nuevos": int}
    No lanza excepcion si el envio real falla -- solo lo deja en el log, para
    que un problema de correo no tumbe el resto del chequeo nocturno.
    """
    if not resumen:
        return

    asunto, cuerpo = _armar_cuerpo(nombre_tenant, resumen)

    if _modo_prueba_activo():
        _guardar_modo_prueba(destinatario, asunto, cuerpo)
        return

    try:
        _enviar_smtp(destinatario, asunto, cuerpo)
        logger.info(f"Correo de resumen enviado a {destinatario} ({len(resumen)} empresas)")
    except Exception as e:
        logger.error(f"No se pudo enviar el correo de resumen a {destinatario}: {e}")


def _guardar_modo_prueba(destinatario: str, asunto: str, cuerpo: str) -> None:
    os.makedirs(DEV_MAIL_DIR, exist_ok=True)
    # Microsegundos (no solo segundos) para que dos correos al mismo
    # destinatario muy seguidos -- p.ej. la alerta del canario y su aviso
    # de "recuperado" -- no se pisen el archivo entre si.
    marca_tiempo = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    nombre_archivo = f"resumen_{marca_tiempo}_{destinatario.replace('@', '_at_')}.txt"
    ruta = os.path.join(DEV_MAIL_DIR, nombre_archivo)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(f"Para: {destinatario}\n")
        f.write(f"Asunto: {asunto}\n")
        f.write("-" * 70 + "\n")
        f.write(cuerpo + "\n")
    logger.info(
        f"[MODO PRUEBA] No hay SMTP configurado -- correo para {destinatario} "
        f"guardado en {ruta} en vez de enviarse de verdad."
    )


def enviar_alerta_canario(destinatario: str, detalle_fallos: list[str], recuperado: bool = False) -> None:
    """
    Fase 3 (confiabilidad/observabilidad): correo al equipo (no a un
    tenant) cuando el chequeo canario detecta que el login a SUNAT dejo de
    funcionar varias veces seguidas -- o, si recuperado=True, cuando vuelve
    a funcionar despues de haber estado en alerta. Mismo doble modo
    (prueba a archivo / SMTP real) que enviar_resumen_diario, y misma
    politica de nunca lanzar excepcion si el envio real falla.
    """
    if recuperado:
        asunto = "Anzen Sol -- el chequeo canario se RECUPERO"
        cuerpo = (
            "El chequeo canario volvio a tener un login exitoso contra SUNAT "
            "despues de haber estado fallando. Ya no deberia hacer falta "
            "ninguna accion, pero vale la pena confirmar en el panel de "
            "Salud del sistema que las consultas normales tambien se "
            "recuperaron."
        )
    else:
        asunto = "Anzen Sol -- ALERTA: el chequeo canario esta fallando"
        lineas = [
            "El chequeo canario (login de prueba periodico contra SUNAT) "
            "fallo varias veces seguidas. Esto suele significar que SUNAT "
            "cambio algo en su portal -- revisar el playbook "
            "(PLAYBOOK_FALLOS_SUNAT.md) para los primeros pasos de "
            "diagnostico.",
            "",
            "Ultimos fallos:",
        ]
        lineas.extend(f"  - {linea}" for linea in detalle_fallos)
        cuerpo = "\n".join(lineas)

    if _modo_prueba_activo():
        _guardar_modo_prueba(destinatario, asunto, cuerpo)
        return

    try:
        _enviar_smtp(destinatario, asunto, cuerpo)
        logger.info(f"Correo de alerta del canario enviado a {destinatario} (recuperado={recuperado})")
    except Exception as e:
        logger.error(f"No se pudo enviar el correo de alerta del canario a {destinatario}: {e}")


def enviar_invitacion_equipo(destinatario: str, nombre_tenant: str, invitado_por_email: str, link: str) -> None:
    """
    Correo con el link para sumarse como usuario adicional al MISMO tenant
    (ver routers/invitaciones.py) -- mismo doble modo (prueba a archivo /
    SMTP real) que el resto de este modulo. A diferencia de los otros dos
    correos, este SI lanza si el envio real falla (el llamador necesita
    saber si la invitacion realmente salio, para poder avisarle a quien la
    genero en vez de que crea que se mando y nunca llegue).
    """
    asunto = f"Te invitaron a unirte a {nombre_tenant} en Anzen Sol"
    cuerpo = (
        f"{invitado_por_email} te invito a sumarte como usuario de {nombre_tenant} "
        "en el tablero de Anzen Sol.\n\n"
        f"Para aceptar la invitacion y crear tu contrasena, entra a:\n{link}\n\n"
        "Este link vence en 7 dias. Si no esperabas esta invitacion, "
        "podes ignorar este correo."
    )

    if _modo_prueba_activo():
        _guardar_modo_prueba(destinatario, asunto, cuerpo)
        return

    _enviar_smtp(destinatario, asunto, cuerpo)
    logger.info(f"Correo de invitacion enviado a {destinatario} (tenant {nombre_tenant})")


def _enviar_smtp(destinatario: str, asunto: str, cuerpo: str) -> None:
    mensaje = MIMEMultipart()
    mensaje["From"] = SMTP_FROM
    mensaje["To"] = destinatario
    mensaje["Subject"] = asunto
    mensaje.attach(MIMEText(cuerpo, "plain", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as servidor:
        servidor.starttls()
        if SMTP_USER:
            servidor.login(SMTP_USER, SMTP_PASSWORD)
        servidor.sendmail(SMTP_FROM, [destinatario], mensaje.as_string())
