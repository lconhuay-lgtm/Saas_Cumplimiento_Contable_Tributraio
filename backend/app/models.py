"""
Modelos SQLAlchemy -- las 6 tablas del esquema aprobado en Fase 0.
Coinciden con el diagrama ERD revisado: TENANTS, USUARIOS, EMPRESAS,
CREDENCIALES_SOL, MENSAJES_BUZON, CONSULTAS_JOBS.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String, Boolean, DateTime, ForeignKey, UniqueConstraint, Integer, LargeBinary, Float, Text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    """Un estudio contable / cuenta que usa la plataforma."""
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    empresas: Mapped[list["Empresa"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class Usuario(Base):
    """Persona que inicia sesion en el tablero, pertenece a un tenant."""
    __tablename__ = "usuarios"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tenants.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[str] = mapped_column(String(20), default="admin", nullable=False)  # admin | miembro
    # Staff de LA PLATAFORMA (nuestro equipo), NO un rol dentro del tenant del
    # cliente -- separado a proposito de `rol` de arriba. Antes de esto,
    # /admin/chequeo-nocturno, /admin/enviar-resumenes, /admin/canario/ejecutar
    # y /admin/reclasificar-mensajes solo exigian estar logueado, sin importar
    # el tenant: cualquier estudio contable registrado podia disparar el
    # chequeo nocturno de TODOS los tenants o forzar la reclasificacion de
    # todos los mensajes de la base (fix Fase R2). Default False -- se marca
    # a mano en la base para las cuentas del equipo operador, nunca desde un
    # endpoint publico.
    es_staff_plataforma: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Fase 5: verificacion de email por link de activacion (punto 10 del
    # plan). NO bloquea el login ni el uso del tablero -- /auth/registro
    # sigue devolviendo el token de acceso igual que siempre, esto solo
    # habilita un aviso + boton "reenviar" en el tablero mientras el usuario
    # no confirme. Los usuarios que ya existian antes de esta migracion
    # quedan marcados como verificados de entrada (ver alembic 0024) para no
    # aparecer de golpe como "sin verificar" sin haber hecho nada distinto.
    email_verificado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Token de un solo uso del link de verificacion -- se regenera cada vez
    # que se reenvia (ver /auth/reenviar-verificacion), asi que un link
    # viejo deja de servir apenas se pide uno nuevo. None una vez verificado.
    token_verificacion: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    token_verificacion_expira: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="usuarios")


class Empresa(Base):
    """Un RUC (cliente) que el tenant quiere monitorear."""
    __tablename__ = "empresas"
    __table_args__ = (UniqueConstraint("tenant_id", "ruc", name="uq_empresa_tenant_ruc"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tenants.id"), nullable=False, index=True)
    ruc: Mapped[str] = mapped_column(String(11), nullable=False, index=True)
    razon_social: Mapped[str] = mapped_column(String(255), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    ultima_consulta_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "Habido" | "No Habido" | "No Hallado" -- leido del navbar del Menu SOL
    # (span.spanEstadoDomicilio) en cada consulta exitosa, igual que la razon
    # social. None hasta la primera consulta que logre leerlo.
    condicion_domicilio: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Valor anterior + cuando cambio -- solo se llenan cuando el valor
    # detectado difiere del que ya estaba guardado (no en la primera
    # deteccion), para poder avisar en el Dashboard de cambios reales sin
    # que la primera consulta de cada empresa cuente como "cambio".
    condicion_domicilio_anterior: Mapped[str | None] = mapped_column(String(20), nullable=True)
    condicion_domicilio_actualizada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "Activo" | "Baja de Oficio" | etc. -- a diferencia de condicion_domicilio,
    # esto NO vive en el navbar normal del Menu SOL, solo dentro de la Ficha
    # RUC (confirmado con un diagnostico real) -- se lee en cada consulta
    # con web_navigation.SunatWebNavigator._leer_estado_contribuyente().
    # Mismo patron de "anterior" + fecha que condicion_domicilio, para el
    # aviso de cambios en el Dashboard.
    estado_contribuyente: Mapped[str | None] = mapped_column(String(30), nullable=True)
    estado_contribuyente_anterior: Mapped[str | None] = mapped_column(String(30), nullable=True)
    estado_contribuyente_actualizado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cuando se INTENTO leer el estado del contribuyente por ultima vez (haya
    # cambiado o no el valor) -- a diferencia de estado_contribuyente_actualizado_en
    # (que solo se toca si el valor cambio), este campo se actualiza en TODA
    # lectura exitosa, y es lo que usa jobs.py para saltarse el paso de la
    # Ficha RUC (~8-10s extra, ver deteccion_estado._leer_estado_contribuyente)
    # en consultas repetidas dentro de la misma ventana de ~20h -- se vuelve
    # a leer solo una vez por dia en vez de en cada consulta individual.
    estado_contribuyente_verificado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Referencia (formato identico a MensajeBuzon.documento_ref, mismo
    # modulo de almacenamiento) al PDF de la Ficha RUC generado mas
    # recientemente -- se sobreescribe cada vez que se vuelve a generar,
    # a diferencia de los documentos de mensajes que se conservan todos.
    ficha_ruc_pdf_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ficha_ruc_generada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "Reporte de Ficha RUC" firmado con codigo QR de verificacion -- un
    # documento DISTINTO al de arriba (SUNAT lo genera por una pantalla
    # separada, "Descargar Ficha RUC"), asi que se guarda aparte en vez de
    # pisar ficha_ruc_pdf_ref. SUNAT limita este a 3 generaciones por dia
    # POR EMPRESA (a partir de la 4ta, devuelve la ultima ya generada sin
    # avisar) -- el conteo diario se calcula sobre FichaRucJob.con_qr, no
    # hace falta duplicarlo aca.
    ficha_ruc_qr_pdf_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ficha_ruc_qr_generada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Fase 3 (confiabilidad/observabilidad): si es True, esta empresa se usa
    # como "cuenta controlada" para el chequeo canario periodico (ver
    # scheduler_job.ejecutar_chequeo_canario) -- una consulta de prueba
    # separada de las consultas normales, solo para medir si el login a
    # SUNAT sigue funcionando. Normalmente una sola empresa del sistema
    # tiene esto en True.
    es_canario: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Modulo de cronograma SUNAT: si es True, esta empresa usa la columna
    # "BUENOS CONTRIBUYENTES y UESP" del cronograma oficial (fecha de
    # vencimiento extendida) en vez de la que le tocaria por su ultimo
    # digito de RUC -- ver app.cronograma_sunat.grupo_para_empresa(). Por
    # defecto False (la gran mayoria de contribuyentes usa el cronograma
    # general).
    es_buen_contribuyente: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Cartera: que usuario del tenant sigue esta empresa (un dueno por
    # empresa, no una lista -- si un estudio necesita compartir una empresa
    # entre varios asistentes, se maneja subiendo esto a una tabla aparte
    # mas adelante, no hace falta ahora). None = sin asignar, cualquier
    # usuario del tenant la sigue viendo igual (esto NO restringe acceso,
    # solo es informativo/filtrable -- la autorizacion real sigue siendo
    # por tenant_id como siempre).
    asignado_a_usuario_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("usuarios.id"), nullable=True, index=True
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="empresas")
    asignado_a: Mapped["Usuario | None"] = relationship(foreign_keys=[asignado_a_usuario_id])
    credencial: Mapped["CredencialSol | None"] = relationship(
        back_populates="empresa", uselist=False, cascade="all, delete-orphan"
    )
    mensajes: Mapped[list["MensajeBuzon"]] = relationship(back_populates="empresa", cascade="all, delete-orphan")
    jobs: Mapped[list["ConsultaJob"]] = relationship(back_populates="empresa", cascade="all, delete-orphan")
    ficha_ruc_jobs: Mapped[list["FichaRucJob"]] = relationship(back_populates="empresa", cascade="all, delete-orphan")
    reporte_tributario_jobs: Mapped[list["ReporteTributarioJob"]] = relationship(back_populates="empresa", cascade="all, delete-orphan")
    canario_checks: Mapped[list["CanarioCheck"]] = relationship(back_populates="empresa", cascade="all, delete-orphan")
    obligaciones: Mapped[list["EmpresaObligacion"]] = relationship(back_populates="empresa", cascade="all, delete-orphan")
    tareas: Mapped[list["TareaObligacion"]] = relationship(back_populates="empresa", cascade="all, delete-orphan")


class CredencialSol(Base):
    """
    Credenciales SOL de una empresa, en tabla aparte a proposito (aislamiento
    de seguridad). clave_cifrada/dek_cifrada son placeholders de Fase 0 --
    Fase 1 semana 5 reemplaza esto por cifrado real via KMS.
    """
    __tablename__ = "credenciales_sol"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    empresa_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("empresas.id"), nullable=False, unique=True
    )
    usuario_sol: Mapped[str] = mapped_column(String(100), nullable=False)
    clave_cifrada: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_cifrada: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    empresa: Mapped["Empresa"] = relationship(back_populates="credencial")


class MensajeBuzon(Base):
    """
    Historial de mensajes leidos del buzon SOL. La restriccion unica sobre
    (empresa_id, mensaje_externo_id) es la que evita el bug de duplicados
    que arreglamos en la automatizacion original -- aqui queda resuelto a
    nivel de base de datos.

    origen: de que bandeja de SUNAT viene -- "notificaciones" (Buzon
      Notificaciones, la bandeja original -- trae PDF adjunto casi
      siempre, documento_ref apunta a ese archivo) o "mensajes" (Buzon
      Mensajes, bandeja separada dentro del mismo Buzon Electronico -- en
      general NO trae PDF, el contenido completo esta en el cuerpo del
      mensaje, guardado en contenido_texto). Ver core_scraper/adapter.py
      (_leer_mensajes_buzon_mensajes) y el diagnostico en vivo del
      25/09/2026 que confirmo la estructura real de esta bandeja.
    contenido_texto: texto completo del mensaje, solo para origen=
      "mensajes" (Buzon Notificaciones no lo necesita, ya tiene su PDF).
    """
    __tablename__ = "mensajes_buzon"
    __table_args__ = (
        UniqueConstraint("empresa_id", "mensaje_externo_id", name="uq_mensaje_empresa_externo"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    empresa_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("empresas.id"), nullable=False, index=True)
    mensaje_externo_id: Mapped[str] = mapped_column(String(500), nullable=False)
    fecha_publicacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    asunto: Mapped[str] = mapped_column(String(500), nullable=False)
    tipo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    leido: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    descubierto_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    documento_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    origen: Mapped[str] = mapped_column(String(20), default="notificaciones", nullable=False)
    contenido_texto: Mapped[str | None] = mapped_column(Text, nullable=True)

    empresa: Mapped["Empresa"] = relationship(back_populates="mensajes")


class ConsultaJob(Base):
    """
    Cola/bitacora de consultas al buzon. Sirve dos propositos: (1) estado del
    job para la cola de trabajos de Fase 1, y (2) auditoria de quien pidio
    entrar a la cuenta SOL de cada empresa y cuando.
    """
    __tablename__ = "consultas_jobs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    empresa_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("empresas.id"), nullable=False, index=True)
    solicitado_por: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("usuarios.id"), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente", nullable=False, index=True)
    # Etapa dentro de "en_progreso" -- iniciando_sesion / autenticando /
    # leyendo_estado / abriendo_buzon / leyendo_mensajes /
    # descargando_documentos -- mismo patron que FichaRucJob.etapa, para
    # que el boton "Consultar" de cada empresa muestre una barra de
    # progreso real en vez de un spinner sin perspectiva de tiempo. None
    # antes de arrancar o una vez que el job ya termino.
    etapa: Mapped[str | None] = mapped_column(String(30), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    iniciado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalizado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mensajes_nuevos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    notificado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    empresa: Mapped["Empresa"] = relationship(back_populates="jobs")


class FichaRucJob(Base):
    """
    Cola/bitacora de generacion de PDF de Ficha RUC -- tabla aparte de
    ConsultaJob a proposito: es una operacion distinta (no lee el Buzon,
    no cuenta mensajes nuevos) y mezclar los dos conceptos en una sola
    tabla con un campo "tipo" hubiera obligado a tocar toda la logica ya
    probada de ConsultaJob. Estructura deliberadamente identica en espiritu
    (mismo patron encolar -> pollear -> resultado) para que sea familiar.
    """
    __tablename__ = "ficha_ruc_jobs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    empresa_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("empresas.id"), nullable=False, index=True)
    solicitado_por: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("usuarios.id"), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente", nullable=False, index=True)
    # Si se pidio el "Reporte de Ficha RUC" firmado con QR (limitado por
    # SUNAT a 3 por dia por empresa) en vez del documento normal (CIR, sin
    # limite conocido) -- ver Empresa.ficha_ruc_qr_pdf_ref. Tambien sirve
    # para calcular cuantos van generados hoy y avisarle al usuario ANTES
    # de que choque con el limite silencioso de SUNAT.
    con_qr: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Etapa dentro de "en_progreso" -- iniciando_sesion / autenticando /
    # abriendo_ficha / generando_pdf / guardando -- solo para darle al
    # usuario una barra de progreso con perspectiva real del tiempo que
    # falta (ver adapter.generar_ficha_ruc_pdf(on_progreso=...)). None
    # antes de arrancar o una vez que el job ya termino (estado ya lo dice).
    etapa: Mapped[str | None] = mapped_column(String(30), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    iniciado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalizado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    empresa: Mapped["Empresa"] = relationship(back_populates="ficha_ruc_jobs")


class ReporteTributarioJob(Base):
    """
    Cola/bitacora de solicitudes del "Reporte Tributario para Terceros"
    (informacion RESERVADA segun el Art. 85 del Codigo Tributario, a
    diferencia de la Ficha RUC que es publica) -- SUNAT lo genera y lo
    manda por su cuenta al correo indicado, no hay ningun PDF que este
    sistema descargue ni guarde: el trabajo del job es solo entrar,
    aceptar el aviso legal, escribir el correo y confirmar el envio.
    SUNAT limita esto a 3 solicitudes por dia por empresa (igual que la
    Ficha RUC con QR) -- a partir de la 4ta, reenvia la ultima ya
    generada sin avisar.
    """
    __tablename__ = "reporte_tributario_jobs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    empresa_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("empresas.id"), nullable=False, index=True)
    solicitado_por: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("usuarios.id"), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente", nullable=False, index=True)
    correo_destino: Mapped[str] = mapped_column(String(255), nullable=False)
    etapa: Mapped[str | None] = mapped_column(String(30), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    iniciado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalizado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    empresa: Mapped["Empresa"] = relationship(back_populates="reporte_tributario_jobs")


class CanarioCheck(Base):
    """
    Fase 3 (confiabilidad/observabilidad): bitacora de cada chequeo
    "canario" -- un login de prueba contra una cuenta controlada
    (Empresa.es_canario=True), disparado periodicamente por el scheduler
    (ver app.scheduler_job.ejecutar_chequeo_canario), SEPARADO de las
    consultas normales de los tenants. El objetivo es medir la salud del
    login a SUNAT de forma proactiva -- que el equipo se entere de un
    cambio en el portal de SUNAT por este chequeo, no por el reclamo de un
    cliente (como paso una vez con la automatizacion original).
    """
    __tablename__ = "canario_checks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    empresa_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("empresas.id"), nullable=False, index=True)
    ejecutado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False, index=True)
    exito: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    duracion_seg: Mapped[float | None] = mapped_column(Float, nullable=True)
    # "flujo1" | "flujo2" | "sin_flujo" -- que pantalla post-login mostro
    # SUNAT esta vez (ver web_navigation._click_condicional). Cambios en la
    # distribucion de estos valores a lo largo del tiempo son una señal
    # temprana de que SUNAT esta modificando su portal, incluso antes de
    # que algo se rompa del todo.
    flujo_detectado: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    empresa: Mapped["Empresa"] = relationship(back_populates="canario_checks")


class CronogramaVencimiento(Base):
    """
    Cronogramas oficiales de SUNAT por ultimo digito de RUC (RS 281-2022,
    vigente de forma permanente desde 2023 -- SUNAT solo republica la tabla
    cada ejercicio en una URL predecible, no cambia la regla). Una fila por
    (periodo_tributario, grupo, tipo): el "grupo" es la columna de la tabla
    oficial segun el ultimo digito del RUC -- "0", "1", "2_3", "4_5", "6_7",
    "8_9" -- o "buenos_contribuyentes" para la columna "BUENOS
    CONTRIBUYENTES y UESP".

    tipo:
      - "mensual" (default): cronograma de Obligaciones Mensuales (Anexo I)
        -- cubre tanto la declaracion de IGV-Renta (PDT/F.621) como PLAME
        (F.601), no hay cronogramas separados para esas dos. Se llena via
        app.cronograma_sunat.sincronizar_cronograma().
      - "sire": cronograma de Atraso de los Registros Electronicos (Anexo
        II) -- fecha maxima para registrar Compras y Ventas e Ingresos
        Electronicos del periodo, SIEMPRE unas semanas despues que la
        fecha "mensual" del mismo periodo+grupo (son dos obligaciones
        distintas, dos filas distintas). Se llena via
        app.cronograma_sire.sincronizar_cronograma_sire().
    """
    __tablename__ = "cronograma_vencimientos"
    __table_args__ = (
        UniqueConstraint("periodo_tributario", "grupo", "tipo", name="uq_cronograma_periodo_grupo_tipo"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    # Periodo tributario que se declara, formato "YYYY-MM" (ej "2026-01" =
    # Ene-2026). NO es la fecha de vencimiento -- esa es fecha_vencimiento.
    periodo_tributario: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    grupo: Mapped[str] = mapped_column(String(30), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), default="mensual", nullable=False)
    fecha_vencimiento: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class EmpresaObligacion(Base):
    """
    Modulo de Tareas/Agenda: que obligaciones RECURRENTES tiene una empresa
    ademas del cronograma general de IGV-Renta/PLAME (que aplica solo con
    estar activa, automatico -- ver cronograma_sunat.py). No todas las
    empresas tienen trabajadores en planilla, ni todas son empleadoras
    afiliadas a AFP, ni todas reportan a la SBS -- aca es donde se marca
    cuales le corresponden a cada una, y con que regla se calcula su
    vencimiento.

    regla_vencimiento:
      - "cronograma_sunat": Planilla, AFP e IGV-Renta comparten EXACTAMENTE
        el mismo cronograma por ultimo digito de RUC que ya usa
        cronograma_sunat.py (Planilla/AFP porque se declaran juntas dentro
        de la PLAME -- confirmado: incluye remuneraciones + aportes AFP/
        ONP/EsSalud/renta 5ta en un solo envio -- e IGV-Renta porque ES ese
        mismo cronograma general) -- no hace falta guardar una fecha
        aparte, se reusa esa tabla.
      - "cronograma_sire": mismo esquema que "cronograma_sunat" (por
        ultimo digito de RUC) pero contra la tabla del cronograma de
        Atraso de Registros Electronicos (CronogramaVencimiento.tipo=
        "sire") -- fecha maxima para registrar Compras/Ventas e Ingresos
        Electronicos, siempre distinta (mas tardia) que la fecha de
        declaracion mensual del mismo periodo. Ver app.cronograma_sire.
      - "dia_fijo_mes": vence un dia fijo de cada mes (columna dia_fijo).
      - "dia_fijo_anual": vence un dia y mes fijo de cada anio (columnas
        dia_fijo + mes_fijo) -- para obligaciones que se repiten una vez
        al anio, no todos los meses (ej. una declaracion jurada anual con
        vencimiento fijo el 15/02).
      - "manual": sin regla automatica -- para reportes SBS, cuyo plazo
        varia mucho segun el tipo de reporte (desde horas hasta dias
        habiles, confirmado investigando) y no sigue ningun cronograma
        fijo. El usuario carga la fecha de vencimiento a mano cada vez.

    meses_activos: filtro OPCIONAL de meses (texto, numeros de mes 1-12
      separados por coma, ej. "5,11") que restringe EN QUE MESES del anio
      se genera la tarea -- se usa junto con "cronograma_sunat" o
      "dia_fijo_mes" (esas dos reglas ya calculan bien la fecha; este
      filtro solo decide en que meses corresponde generarla). None/vacio
      = todos los meses (default, compatible con lo que ya existia antes
      de este campo). Cubre cualquier periodicidad -- bimestral,
      trimestral, semestral, personalizada -- sin necesitar una regla
      nueva por cada caso:
        - CTS (deposito semestral, 15 de mayo y 15 de noviembre):
          regla_vencimiento="dia_fijo_mes", dia_fijo=15,
          meses_activos="5,11".
        - ITAN pagado en 9 cuotas (abril a diciembre, mismo cronograma
          por RUC que IGV-Renta/PLAME): regla_vencimiento="cronograma_sunat",
          meses_activos="4,5,6,7,8,9,10,11,12".
      No se usa junto con "dia_fijo_anual" (esa regla ya trae su propio
      mes fijo via mes_fijo) ni con "manual" (no calcula fecha).
    """
    __tablename__ = "empresa_obligaciones"
    __table_args__ = (
        UniqueConstraint("empresa_id", "tipo", "nombre", name="uq_empresa_obligacion_tipo_nombre"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    empresa_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("empresas.id"), nullable=False, index=True)
    # "igv_renta" | "planilla" | "afp" | "sbs" | "cts" | "itan" | "sire" | "otro"
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    regla_vencimiento: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    dia_fijo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Solo para regla_vencimiento="dia_fijo_anual" -- mes (1-12) en el que
    # cae el vencimiento cada anio. None para las demas reglas.
    mes_fijo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Filtro opcional de meses (ver docstring de la clase) -- "5,11" para
    # CTS, "4,5,...,12" para ITAN en 9 cuotas, etc. None = todos los meses.
    meses_activos: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Prioridad por defecto de las tareas que genere esta obligacion --
    # baja|media|alta|urgente, mismo vocabulario que TareaObligacion.prioridad
    # (ver esa clase). Se copia a cada TareaObligacion en el momento de
    # generarla (app.tareas.generar_tareas_mes); cambiarla despues no
    # reescribe las tareas ya generadas, solo aplica a las nuevas.
    prioridad: Mapped[str] = mapped_column(String(20), default="media", nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    empresa: Mapped["Empresa"] = relationship(back_populates="obligaciones")
    tareas: Mapped[list["TareaObligacion"]] = relationship(back_populates="obligacion", cascade="all, delete-orphan")


class TareaObligacion(Base):
    """
    Modulo de Tareas/Agenda: una tarea concreta con fecha limite -- generada
    automaticamente a partir de una EmpresaObligacion (planilla/AFP via el
    cronograma SUNAT, o una regla de dia fijo), o creada suelta a mano
    (empresa_obligacion_id=None) para pendientes puntuales tipo "responder
    esquela de SUNAT" o un reporte SBS con su fecha cargada a mano.
    """
    __tablename__ = "tarea_obligaciones"
    __table_args__ = (
        UniqueConstraint("empresa_obligacion_id", "periodo", name="uq_tarea_obligacion_periodo"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    empresa_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("empresas.id"), nullable=False, index=True)
    empresa_obligacion_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("empresa_obligaciones.id"), nullable=True, index=True
    )
    # De que notificacion del buzon nacio esta tarea, si nacio de una (el
    # usuario decide crearla desde el detalle de un mensaje puntual, con la
    # fecha real que diga el documento -- el sistema nunca inventa un plazo
    # legal). Unique: una notificacion genera como maximo una tarea, para
    # que el boton "Crear tarea" del mensaje se pueda convertir en "Ver
    # tarea" sin duplicar si se aprieta mas de una vez.
    mensaje_buzon_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("mensajes_buzon.id"), nullable=True, unique=True
    )
    titulo: Mapped[str] = mapped_column(String(300), nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)  # planilla|afp|sbs|otro|manual|notificacion
    periodo: Mapped[str | None] = mapped_column(String(7), nullable=True)  # "2026-08", None si no aplica
    fecha_vencimiento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente", nullable=False, index=True)  # pendiente|completado|no_aplica
    prioridad: Mapped[str] = mapped_column(String(20), default="media", nullable=False)  # baja|media|alta|urgente
    proceso: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)  # automatica|manual
    fecha_completado: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observaciones: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    empresa: Mapped["Empresa"] = relationship(back_populates="tareas")
    obligacion: Mapped["EmpresaObligacion | None"] = relationship(back_populates="tareas")
    mensaje: Mapped["MensajeBuzon | None"] = relationship()


class InvitacionUsuario(Base):
    """
    Invitacion para sumar un usuario adicional al MISMO tenant -- a
    diferencia de /auth/registro (siempre crea un tenant nuevo), esto es
    la puerta de entrada para que un cliente con varios usuarios (ej. un
    estudio contable con un socio + un asistente) los conecte a la misma
    cuenta en vez de terminar con un tenant por persona.

    No hay una restriccion UNIQUE de (tenant_id, email) a proposito: una
    invitacion cancelada o expirada no debe bloquear una nueva invitacion
    al mismo email despues -- eso se valida en el router, revisando si ya
    hay una invitacion pendiente (usado_en/cancelado_en ambos None y
    todavia no expiro) antes de crear una nueva.
    """
    __tablename__ = "invitaciones_usuario"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tenants.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    invitado_por_usuario_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("usuarios.id"), nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped["Tenant"] = relationship()


class ConfiguracionSistema(Base):
    """
    Fase 5: "panel maestro" -- ajustes operativos GLOBALES (no por tenant,
    todos comparten el mismo scraper/worker), editables desde el tablero
    por el equipo de la plataforma (ver deps.get_staff_actual) sin necesitar
    redeploy para cambiar un numero. Antes de esto, limite_mensajes/
    espaciado/concurrencia_maxima solo se podian tocar editando variables
    de entorno y reiniciando los contenedores.

    Fila unica (id fijo "global") -- no hace falta una tabla clave/valor
    generica para 4 numeros. Ver app.rate_limit para como se leen estos
    valores en tiempo real (con fallback a las variables de entorno de
    siempre si esta fila todavia no existe) y donde se usa cada uno:
      - limite_mensajes_por_consulta: cuantos mensajes del Buzon de
        Notificaciones lee como maximo cada consulta (adapter.consultar_buzon).
      - espaciado_seg_entre_consultas: segundos entre cada empresa de una
        tanda (chequeo nocturno, "Consultar todas", importacion masiva).
      - concurrencia_maxima: cuantas sesiones de Selenium contra SUNAT
        pueden correr en paralelo en todo el sistema.
      - segundos_entre_consultas_mismo_ruc: minimo entre dos consultas de
        LA MISMA empresa (rate_limit.verificar_limite_ruc).
    """
    __tablename__ = "configuracion_sistema"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=lambda: "global")
    limite_mensajes_por_consulta: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    espaciado_seg_entre_consultas: Mapped[int] = mapped_column(Integer, default=45, nullable=False)
    concurrencia_maxima: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    segundos_entre_consultas_mismo_ruc: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
    actualizado_por_usuario_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("usuarios.id"), nullable=True
    )
