"""Schemas Pydantic -- validacion de entrada/salida de la API."""
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class RegistroRequest(BaseModel):
    nombre_tenant: str = Field(..., min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UsuarioResponse(BaseModel):
    id: str
    email: EmailStr
    rol: str
    tenant_id: str

    class Config:
        from_attributes = True


class EmpresaCreate(BaseModel):
    ruc: str = Field(..., min_length=11, max_length=11, pattern=r"^\d{11}$")
    razon_social: str = Field(..., min_length=1, max_length=255)
    usuario_sol: str = Field(..., min_length=1, max_length=100)
    clave_sol: str = Field(..., min_length=1, max_length=200)
    # A pedido: elegir de entrada que obligaciones recurrentes le
    # corresponden a esta empresa, en vez de tener que configurarlas
    # despues a mano en una pantalla aparte -- ver
    # app.routers.empresas._crear_obligaciones_por_defecto. IGV-Renta
    # viene marcado por defecto (le corresponde a casi todas las
    # empresas activas); PLAME y SBS no (no todas tienen trabajadores en
    # planilla o reportan a la SBS).
    obligacion_igv_renta: bool = True
    obligacion_plame: bool = False
    obligacion_sbs: bool = False
    # Fase 2: dos obligaciones mas con periodicidad no-mensual, a modo de
    # ejemplo concreto de "recurrencia flexible" (ver
    # app.routers.empresas._crear_obligaciones_por_defecto). No todas las
    # empresas las tienen, asi que ambas vienen sin marcar por defecto.
    obligacion_cts: bool = False
    obligacion_itan: bool = False


class UltimoMensajeResumen(BaseModel):
    id: str
    asunto: str
    tipo: str | None
    tiene_documento: bool
    fecha_publicacion: datetime


class EmpresaResponse(BaseModel):
    id: str
    ruc: str
    razon_social: str
    activo: bool
    creado_en: datetime
    ultima_consulta_en: datetime | None
    pendientes: int = 0
    total_mensajes: int = 0
    total_consultas: int = 0
    mensajes_hoy: int = 0
    ultimo_mensaje: UltimoMensajeResumen | None = None
    condicion_domicilio: str | None = None
    estado_contribuyente: str | None = None
    ficha_ruc_generada_en: datetime | None = None
    ficha_ruc_qr_generada_en: datetime | None = None
    # Fase 3: si esta empresa es la "cuenta controlada" usada por el
    # chequeo canario (ver app.scheduler_job.ejecutar_chequeo_canario).
    es_canario: bool = False
    # Modulo de cronograma SUNAT: si usa la fecha extendida de "Buenos
    # Contribuyentes y UESP" en vez del cronograma general por ultimo
    # digito de RUC (ver app.cronograma_sunat.grupo_para_empresa).
    es_buen_contribuyente: bool = False
    # Cartera: usuario del tenant que sigue esta empresa (None = sin
    # asignar). Ver Usuario.asignado_a_usuario_id en models.py -- es
    # informativo/filtrable, no restringe quien puede ver la empresa.
    asignado_a_usuario_id: str | None = None

    class Config:
        from_attributes = True


class EmpresaUpdate(BaseModel):
    activo: bool
    # Opcionales -- si no se mandan, no se tocan (permite que el toggle de
    # "activo" siga funcionando exactamente igual que antes).
    es_canario: bool | None = None
    es_buen_contribuyente: bool | None = None
    # None es un valor VALIDO aca (significa "desasignar") -- el handler en
    # routers/empresas.py distingue "no vino en el request" de "vino como
    # null" via model_fields_set, no con este default.
    asignado_a_usuario_id: str | None = None


class EmpresaCredencialesUpdate(BaseModel):
    """Cambiar el usuario/clave SOL guardados de una empresa -- endpoint
    separado de EmpresaUpdate a proposito, mismo criterio que credenciales_sol
    es su propia tabla (aislamiento de lo sensible)."""
    usuario_sol: str = Field(..., min_length=1, max_length=100)
    clave_sol: str = Field(..., min_length=1, max_length=200)


class JobResponse(BaseModel):
    id: str
    empresa_id: str
    estado: str
    etapa: str | None = None
    creado_en: datetime
    iniciado_en: datetime | None
    finalizado_en: datetime | None
    mensajes_nuevos: int
    error: str | None

    class Config:
        from_attributes = True


class FichaRucJobResponse(BaseModel):
    id: str
    empresa_id: str
    estado: str
    etapa: str | None = None
    con_qr: bool
    creado_en: datetime
    iniciado_en: datetime | None
    finalizado_en: datetime | None
    error: str | None

    class Config:
        from_attributes = True


class LimiteDiarioResponse(BaseModel):
    usados_hoy: int
    limite: int


class ReporteTributarioCreate(BaseModel):
    correo_destino: EmailStr


class ReporteTributarioJobResponse(BaseModel):
    id: str
    empresa_id: str
    estado: str
    etapa: str | None = None
    correo_destino: str
    creado_en: datetime
    iniciado_en: datetime | None
    finalizado_en: datetime | None
    error: str | None

    class Config:
        from_attributes = True


class MensajeBuzonResponse(BaseModel):
    id: str
    fecha_publicacion: datetime
    asunto: str
    tipo: str | None
    leido: bool
    descubierto_en: datetime
    tiene_documento: bool = False

    class Config:
        from_attributes = True


class MensajeUpdate(BaseModel):
    leido: bool


class MarcarLeidosResponse(BaseModel):
    actualizados: int


class EmpresaPendienteResumen(BaseModel):
    id: str
    ruc: str
    razon_social: str
    pendientes: int


class ActividadRecienteItem(BaseModel):
    empresa_id: str
    empresa_ruc: str
    empresa_razon_social: str
    estado: str
    mensajes_nuevos: int
    finalizado_en: datetime | None
    error: str | None


class CambioDomicilioItem(BaseModel):
    empresa_id: str
    empresa_ruc: str
    empresa_razon_social: str
    condicion_anterior: str | None
    condicion_actual: str
    actualizada_en: datetime


class CambioEstadoContribuyenteItem(BaseModel):
    empresa_id: str
    empresa_ruc: str
    empresa_razon_social: str
    estado_anterior: str | None
    estado_actual: str
    actualizada_en: datetime


class VencimientoAgendaItem(BaseModel):
    """Un vencimiento de declaracion mensual (IGV-Renta/PLAME) que le toca a
    una empresa, segun el cronograma oficial de SUNAT y su ultimo digito de
    RUC (o su fecha extendida si es Buen Contribuyente/UESP)."""
    empresa_id: str
    empresa_ruc: str
    empresa_razon_social: str
    periodo_tributario: str
    grupo: str
    fecha_vencimiento: datetime


class ProximoVencimientoItem(VencimientoAgendaItem):
    dias_restantes: int


class DashboardResumen(BaseModel):
    empresas_activas: int
    empresas_totales: int
    pendientes_totales: int
    mensajes_hoy_totales: int = 0
    empresas_con_novedades_hoy: int = 0
    empresas_con_pendientes: list[EmpresaPendienteResumen]
    actividad_reciente: list[ActividadRecienteItem]
    cambios_domicilio_recientes: list[CambioDomicilioItem] = []
    cambios_estado_contribuyente_recientes: list[CambioEstadoContribuyenteItem] = []
    # Modulo de cronograma SUNAT: proximos vencimientos de declaracion
    # mensual (IGV-Renta/PLAME) dentro de los proximos dias -- ver
    # app.cronograma_sunat.proximos_vencimientos_por_tenant.
    proximos_vencimientos: list[ProximoVencimientoItem] = []


class EmpresaEnProgresoItem(BaseModel):
    """A pedido: que empresa(s) puntual(es) esta consultando el worker AHORA MISMO, no solo el conteo agregado."""
    empresa_id: str
    empresa_ruc: str
    empresa_razon_social: str
    etapa: str | None = None


class EstadoConsultasResponse(BaseModel):
    en_curso: bool
    total: int = 0
    completados: int = 0
    en_progreso: int = 0
    pendientes: int = 0
    con_error: int = 0
    iniciado_en: datetime | None = None
    empresas_en_progreso: list[EmpresaEnProgresoItem] = []


class EmpresaImportadaItem(BaseModel):
    ruc: str
    razon_social: str
    resultado: str
    detalle: str | None = None


class ImportarEmpresasResponse(BaseModel):
    creadas: int
    ya_existian: int
    con_error: int
    detalle: list[EmpresaImportadaItem]


class SaludCanarioPorFlujo(BaseModel):
    """Fase 3: tasa de exito y duracion promedio del canario, desglosada
    por el tipo de pantalla post-login que mostro SUNAT (ver
    web_navigation._click_condicional) -- un cambio en esta distribucion a
    lo largo del tiempo es una senal temprana de que SUNAT esta
    modificando su portal."""
    flujo: str
    total: int
    exitosos: int
    tasa_exito: float
    duracion_prom_seg: float | None = None


class SaludCanarioResumen(BaseModel):
    tiene_empresa_canario: bool
    en_alerta: bool
    total_checks: int
    ultimo_check_en: datetime | None = None
    ultimo_resultado: bool | None = None
    por_flujo: list[SaludCanarioPorFlujo] = []


class SaludConsultasResumen(BaseModel):
    total: int
    exitosas: int
    fallidas: int
    tasa_exito: float | None = None
    duracion_prom_seg: float | None = None


class SaludResponse(BaseModel):
    """Fase 3 (semana 9): panel simple de salud -- pensado para enterarse
    de un cambio en el portal de SUNAT por este panel, no por el reclamo
    de un cliente."""
    periodo_horas: int
    canario: SaludCanarioResumen
    consultas: SaludConsultasResumen


class ErrorRecienteItem(BaseModel):
    tipo: str  # "canario" | "consulta"
    empresa_ruc: str | None = None
    empresa_razon_social: str | None = None
    ocurrido_en: datetime | None = None
    error: str | None = None


class CronogramaSincronizarResponse(BaseModel):
    anio: int
    periodos_procesados: int
    filas_guardadas: int


class AgendaMesResponse(BaseModel):
    anio: int
    mes: int
    vencimientos: list[VencimientoAgendaItem]


_PATRON_MESES_ACTIVOS = r"^(1[0-2]|[1-9])(,(1[0-2]|[1-9]))*$"


_PATRON_PRIORIDAD = r"^(baja|media|alta|urgente)$"


class EmpresaObligacionCreate(BaseModel):
    tipo: str = Field(..., pattern=r"^(igv_renta|planilla|afp|sbs|cts|itan|otro)$")
    nombre: str = Field(..., min_length=1, max_length=200)
    activa: bool = True
    regla_vencimiento: str = Field("manual", pattern=r"^(cronograma_sunat|dia_fijo_mes|dia_fijo_anual|manual)$")
    dia_fijo: int | None = Field(None, ge=1, le=31)
    mes_fijo: int | None = Field(None, ge=1, le=12)
    meses_activos: str | None = Field(None, pattern=_PATRON_MESES_ACTIVOS)
    prioridad: str = Field("media", pattern=_PATRON_PRIORIDAD)


class EmpresaObligacionUpdate(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=200)
    activa: bool | None = None
    regla_vencimiento: str | None = Field(None, pattern=r"^(cronograma_sunat|dia_fijo_mes|dia_fijo_anual|manual)$")
    dia_fijo: int | None = Field(None, ge=1, le=31)
    mes_fijo: int | None = Field(None, ge=1, le=12)
    meses_activos: str | None = Field(None, pattern=_PATRON_MESES_ACTIVOS)
    prioridad: str | None = Field(None, pattern=_PATRON_PRIORIDAD)


class EmpresaObligacionResponse(BaseModel):
    id: str
    empresa_id: str
    tipo: str
    nombre: str
    activa: bool
    regla_vencimiento: str
    dia_fijo: int | None
    mes_fijo: int | None
    meses_activos: str | None
    prioridad: str
    creado_en: datetime

    class Config:
        from_attributes = True


class TareaObligacionResponse(BaseModel):
    id: str
    empresa_id: str
    empresa_ruc: str
    empresa_razon_social: str
    empresa_obligacion_id: str | None
    # De que mensaje del buzon nacio esta tarea, si nacio de una (None para
    # las del cronograma/obligaciones recurrentes o las sueltas a mano).
    mensaje_buzon_id: str | None = None
    # Cartera: quien sigue la empresa dueña de esta tarea -- se hereda de
    # Empresa.asignado_a_usuario_id, no se guarda por separado en la tarea
    # (asi que reasignar la empresa reasigna automaticamente sus tareas,
    # sin tener que tocarlas una por una).
    empresa_asignado_a_usuario_id: str | None = None
    titulo: str
    tipo: str
    periodo: str | None
    fecha_vencimiento: datetime | None
    estado: str
    prioridad: str
    proceso: str
    fecha_completado: datetime | None
    observaciones: str | None
    creado_en: datetime


class TareaObligacionUpdate(BaseModel):
    estado: str | None = Field(None, pattern=r"^(pendiente|completado|no_aplica)$")
    prioridad: str | None = Field(None, pattern=r"^(baja|media|alta|urgente)$")
    fecha_vencimiento: datetime | None = None
    observaciones: str | None = Field(None, max_length=2000)


class TareaObligacionCreate(BaseModel):
    empresa_id: str
    titulo: str = Field(..., min_length=1, max_length=300)
    tipo: str = Field("otro", max_length=30)
    fecha_vencimiento: datetime | None = None
    prioridad: str = Field("media", pattern=r"^(baja|media|alta|urgente)$")
    observaciones: str | None = Field(None, max_length=2000)
    # Si se manda, la tarea queda vinculada a esa notificacion del buzon (ver
    # POST /empresas/{empresa_id}/mensajes/{mensaje_id}/... en el frontend --
    # el mensaje debe pertenecer a la MISMA empresa, se valida en el router).
    mensaje_buzon_id: str | None = None


class GenerarTareasResponse(BaseModel):
    periodo: str
    tareas_creadas: int
    obligaciones_sin_regla: int


class AvancePorTipo(BaseModel):
    """Un renglon del panel 'Avance de Cumplimiento' del Dashboard -- cuantas
    tareas de este tipo hay para el periodo pedido y cuantas ya se
    completaron."""
    tipo: str
    total: int
    completados: int
    avance: float  # 0.0 a 100.0


class AvanceCumplimientoResponse(BaseModel):
    periodo: str
    por_tipo: list[AvancePorTipo]
    total: AvancePorTipo


class DocumentoRecienteItem(BaseModel):
    """Fase 3.5: para la vista de "Documentos recientes" de Salud del
    sistema -- un vistazo rapido a los ultimos PDFs que el scraper bajo,
    de cualquier empresa del tenant, para verificar de un vistazo que la
    descarga de documentos sigue funcionando."""
    mensaje_id: str
    empresa_id: str
    empresa_ruc: str
    empresa_razon_social: str
    asunto: str
    tipo: str | None = None
    fecha_publicacion: datetime
    descubierto_en: datetime


class InvitacionCreate(BaseModel):
    email: EmailStr


class InvitacionResponse(BaseModel):
    id: str
    email: str
    invitado_por_email: str
    link: str
    creado_en: datetime
    expira_en: datetime
    usado_en: datetime | None
    cancelado_en: datetime | None


class InvitacionAceptarRequest(BaseModel):
    password: str = Field(..., min_length=8)


class InvitacionInfoPublica(BaseModel):
    """Lo que ve la pantalla publica /invitacion/{token} ANTES de aceptar --
    a proposito no expone nada mas del tenant que su nombre."""
    valido: bool
    motivo_invalido: str | None = None
    tenant_nombre: str | None = None
    email: str | None = None
