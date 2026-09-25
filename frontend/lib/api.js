/**
 * Cliente unico de la API del backend. Guarda el JWT en localStorage (esto
 * es un tablero SPA, no hay sesiones de servidor en Next.js) y lo agrega
 * como header Authorization en cada request. Si el backend responde 401
 * (token vencido o invalido), limpia la sesion y manda al usuario de vuelta
 * al login -- asi ninguna pagina necesita repetir esa logica.
 */
export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function getToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("buzon_token");
}

export function setToken(token) {
  window.localStorage.setItem("buzon_token", token);
}

export function clearToken() {
  window.localStorage.removeItem("buzon_token");
}

async function apiFetch(path, options = {}) {
  const token = getToken();
  const esFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers = {
    // Con FormData (subir archivos) el navegador arma su propio
    // Content-Type con el boundary correcto -- si lo fijamos nosotros a
    // mano el request sale mal formado.
    ...(esFormData ? {} : { "Content-Type": "application/json" }),
    ...(options.headers || {}),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Sesion expirada, inicia sesion de nuevo.");
  }

  if (!res.ok) {
    let detalle = `Error ${res.status}`;
    try {
      const data = await res.json();
      detalle = data.detail || JSON.stringify(data);
    } catch (e) {
      // el cuerpo no era JSON, se usa el detalle generico
    }
    throw new Error(detalle);
  }

  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  login: (email, password) =>
    apiFetch("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),

  registro: (nombreTenant, email, password) =>
    apiFetch("/auth/registro", {
      method: "POST",
      body: JSON.stringify({ nombre_tenant: nombreTenant, email, password }),
    }),

  // Invitar un usuario adicional al MISMO tenant (equipo).
  listarInvitaciones: () => apiFetch("/invitaciones"),

  crearInvitacion: (email) => apiFetch("/invitaciones", { method: "POST", body: JSON.stringify({ email }) }),

  cancelarInvitacion: (id) => apiFetch(`/invitaciones/${id}`, { method: "DELETE" }),

  // Publicos (sin token) -- para quien recibe el link de invitacion.
  infoInvitacion: (token) => apiFetch(`/invitaciones/${token}/info`),

  aceptarInvitacion: (token, password) =>
    apiFetch(`/invitaciones/${token}/aceptar`, { method: "POST", body: JSON.stringify({ password }) }),

  me: () => apiFetch("/auth/me"),

  // Fase 5: verificacion de email (link de activacion, no bloquea el login).
  reenviarVerificacion: () => apiFetch("/auth/reenviar-verificacion", { method: "POST" }),

  // Publico (sin token) -- para quien hace clic en el link del correo.
  verificarEmail: (token) => apiFetch(`/auth/verificar-email/${token}`, { method: "POST" }),

  // Cartera: usuarios del propio tenant, para el selector de "asignar a".
  listarUsuarios: () => apiFetch("/usuarios"),

  listarEmpresas: () => apiFetch("/empresas"),

  obtenerEmpresa: (id) => apiFetch(`/empresas/${id}`),

  crearEmpresa: (data) => apiFetch("/empresas", { method: "POST", body: JSON.stringify(data) }),

  actualizarEmpresa: (id, data) =>
    apiFetch(`/empresas/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  actualizarCredencialesEmpresa: (id, usuarioSol, claveSol) =>
    apiFetch(`/empresas/${id}/credenciales`, {
      method: "PATCH",
      body: JSON.stringify({ usuario_sol: usuarioSol, clave_sol: claveSol }),
    }),

  eliminarEmpresa: (id) => apiFetch(`/empresas/${id}`, { method: "DELETE" }),

  consultarEmpresa: (id) => apiFetch(`/empresas/${id}/consultar`, { method: "POST" }),

  consultarTodas: () => apiFetch("/empresas/consultar-todas", { method: "POST" }),

  estadoConsultas: () => apiFetch("/consultas/estado"),

  obtenerJob: (jobId) => apiFetch(`/jobs/${jobId}`),

  listarJobsDeEmpresa: (empresaId) => apiFetch(`/empresas/${empresaId}/jobs`),

  listarMensajes: (empresaId) => apiFetch(`/empresas/${empresaId}/mensajes`),

  marcarLeido: (empresaId, mensajeId, leido) =>
    apiFetch(`/empresas/${empresaId}/mensajes/${mensajeId}`, {
      method: "PATCH",
      body: JSON.stringify({ leido }),
    }),

  marcarTodosLeidos: (empresaId) =>
    apiFetch(`/empresas/${empresaId}/mensajes/marcar-leidos`, { method: "POST" }),

  /**
   * Version global de marcarTodosLeidos -- marca como leidos TODOS los
   * mensajes pendientes de TODAS las empresas del tenant de una sola vez.
   */
  marcarTodosLeidosGlobal: () => apiFetch("/empresas/marcar-todos-leidos", { method: "POST" }),

  dashboardResumen: () => apiFetch("/dashboard/resumen"),
  // (sin cambios -- el endpoint ya devuelve cambios_domicilio_recientes)

  // Fase 3 (confiabilidad/observabilidad): panel de salud del sistema.
  obtenerSalud: (horasAtras = 24 * 7) => apiFetch(`/admin/salud?horas_atras=${horasAtras}`),

  obtenerErroresRecientes: (limite = 20) => apiFetch(`/admin/errores-recientes?limite=${limite}`),

  // Ultimos N documentos (PDFs) descargados, de cualquier empresa del
  // tenant -- revision rapida de que la descarga de documentos funciona.
  obtenerDocumentosRecientes: (limite = 10) => apiFetch(`/admin/documentos-recientes?limite=${limite}`),

  ejecutarCanario: () => apiFetch("/admin/canario/ejecutar", { method: "POST" }),

  // Fase 5: "panel maestro" -- ajustes operativos globales, solo staff de la plataforma.
  obtenerConfiguracionSistema: () => apiFetch("/admin/configuracion"),

  actualizarConfiguracionSistema: (data) =>
    apiFetch("/admin/configuracion", { method: "PUT", body: JSON.stringify(data) }),

  /**
   * "Ingreso directo": pide un token de un solo uso (dura 2 minutos) para
   * abrir una pestaña ya logueada en Operaciones en Linea de SUNAT, sin
   * escribir nada. Quien llama a esto debe abrir la pestaña con
   * `${API_URL}/empresas/{id}/ingreso-directo?token=...` -- esa segunda
   * llamada es una navegacion comun del navegador (no pasa por apiFetch,
   * no lleva el header Authorization, por eso el token va en la URL).
   */
  obtenerTokenIngresoDirecto: (empresaId) =>
    apiFetch(`/empresas/${empresaId}/ingreso-directo/token`, { method: "POST" }),

  /** Igual que obtenerTokenIngresoDirecto, pero para "Ir a Declaraciones y Pagos" (destino distinto, mismo mecanismo). */
  obtenerTokenIngresoDirectoDeclaraciones: (empresaId) =>
    apiFetch(`/empresas/${empresaId}/ingreso-directo-declaraciones/token`, { method: "POST" }),

  /**
   * Dispara en segundo plano un "pre-calentado" del ingreso directo (ver
   * backend/app/ingreso_directo_cache.py) -- se llama una vez al abrir la
   * lista de empresas para que, si el usuario hace clic en "Ir a SUNAT"
   * unos segundos/minutos despues, el ticket ya este listo y el clic sea
   * casi instantaneo. Fire-and-forget: a quien llama no le interesa la
   * respuesta ni le importa si falla (el flujo normal sigue funcionando
   * igual sin esto).
   */
  prewarmIngresoDirecto: () => apiFetch("/empresas/ingreso-directo/prewarm", { method: "POST" }),

  generarFichaRuc: (empresaId, conQr = false) =>
    apiFetch(`/empresas/${empresaId}/ficha-ruc?con_qr=${conQr}`, { method: "POST" }),

  obtenerJobFichaRuc: (empresaId, jobId) =>
    apiFetch(`/empresas/${empresaId}/ficha-ruc/jobs/${jobId}`),

  obtenerLimiteQrFichaRuc: (empresaId) => apiFetch(`/empresas/${empresaId}/ficha-ruc/limite-qr`),

  /**
   * Igual que obtenerDocumentoUrl: hay que pasar por fetch() con el header
   * Authorization porque un <iframe>/<a> no lo manda solo. Quien use esto
   * debe llamar URL.revokeObjectURL(url) cuando termine.
   */
  obtenerFichaRucPdfUrl: async (empresaId, conQr = false) => {
    const token = getToken();
    const res = await fetch(`${API_URL}/empresas/${empresaId}/ficha-ruc/pdf?con_qr=${conQr}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      let detalle = `No se pudo cargar la Ficha RUC (${res.status})`;
      try {
        const data = await res.json();
        detalle = data.detail || detalle;
      } catch (e) {
        // sin cuerpo JSON, se usa el detalle generico
      }
      throw new Error(detalle);
    }
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },

  generarReporteTributario: (empresaId, correoDestino) =>
    apiFetch(`/empresas/${empresaId}/reporte-tributario`, {
      method: "POST",
      body: JSON.stringify({ correo_destino: correoDestino }),
    }),

  obtenerJobReporteTributario: (empresaId, jobId) =>
    apiFetch(`/empresas/${empresaId}/reporte-tributario/jobs/${jobId}`),

  obtenerLimiteReporteTributario: (empresaId) => apiFetch(`/empresas/${empresaId}/reporte-tributario/limite`),

  // Modulo de cronograma SUNAT: sincronizar a mano (por si SUNAT publica
  // una modificacion a mitad de ano), agenda por mes (calendario), y
  // proximos vencimientos (aviso del Dashboard).
  sincronizarCronograma: (anio) =>
    apiFetch(`/cronograma/sincronizar${anio ? `?anio=${anio}` : ""}`, { method: "POST" }),

  // Fase 4: mismo cronograma, version "Atraso de Registros Electronicos"
  // (SIRE) -- ver backend/app/cronograma_sire.py.
  sincronizarCronogramaSire: (anio) =>
    apiFetch(`/cronograma/sincronizar-sire${anio ? `?anio=${anio}` : ""}`, { method: "POST" }),

  obtenerAgendaMes: (anio, mes, tipo = "mensual") =>
    apiFetch(`/cronograma/agenda?anio=${anio}&mes=${mes}&tipo=${tipo}`),

  obtenerProximosVencimientos: (diasAdelante = 15, tipo = "mensual") =>
    apiFetch(`/cronograma/proximos?dias_adelante=${diasAdelante}&tipo=${tipo}`),

  // Modulo de Tareas/Agenda: obligaciones configurables por empresa
  // (Planilla/AFP/SBS/otro -- no todas las empresas tienen todas) + las
  // tareas concretas generadas a partir de esas reglas, mas tareas sueltas
  // creadas a mano.
  listarObligaciones: (empresaId) => apiFetch(`/empresas/${empresaId}/obligaciones`),

  crearObligacion: (empresaId, data) =>
    apiFetch(`/empresas/${empresaId}/obligaciones`, { method: "POST", body: JSON.stringify(data) }),

  actualizarObligacion: (obligacionId, data) =>
    apiFetch(`/obligaciones/${obligacionId}`, { method: "PATCH", body: JSON.stringify(data) }),

  eliminarObligacion: (obligacionId) => apiFetch(`/obligaciones/${obligacionId}`, { method: "DELETE" }),

  listarTareas: (filtros = {}) => {
    const params = new URLSearchParams();
    if (filtros.estado) params.set("estado", filtros.estado);
    if (filtros.empresaId) params.set("empresa_id", filtros.empresaId);
    if (filtros.periodo) params.set("periodo", filtros.periodo);
    if (filtros.asignadoAUsuarioId) params.set("asignado_a_usuario_id", filtros.asignadoAUsuarioId);
    if (filtros.fechaDesde) params.set("fecha_desde", filtros.fechaDesde);
    if (filtros.fechaHasta) params.set("fecha_hasta", filtros.fechaHasta);
    if (filtros.mensajeBuzonId) params.set("mensaje_buzon_id", filtros.mensajeBuzonId);
    const qs = params.toString();
    return apiFetch(`/tareas${qs ? `?${qs}` : ""}`);
  },

  crearTareaManual: (data) => apiFetch("/tareas", { method: "POST", body: JSON.stringify(data) }),

  actualizarTarea: (tareaId, data) =>
    apiFetch(`/tareas/${tareaId}`, { method: "PATCH", body: JSON.stringify(data) }),

  eliminarTarea: (tareaId) => apiFetch(`/tareas/${tareaId}`, { method: "DELETE" }),

  generarTareas: (anio, mes) => apiFetch(`/tareas/generar?anio=${anio}&mes=${mes}`, { method: "POST" }),

  obtenerAvanceCumplimiento: (periodo) => apiFetch(`/tareas/avance-cumplimiento?periodo=${periodo}`),

  importarEmpresas: (archivo) => {
    const formData = new FormData();
    formData.append("archivo", archivo);
    return apiFetch("/empresas/importar", { method: "POST", body: formData });
  },

  /**
   * Devuelve una blob URL local con el PDF, lista para usar en un <iframe
   * src="...">. No se puede apuntar el iframe directo al endpoint del
   * backend porque un iframe no manda el header Authorization -- por eso
   * se pide el archivo con fetch() (que si lo manda) y se arma la URL a
   * partir de la respuesta. Quien use esto debe llamar
   * URL.revokeObjectURL(url) cuando ya no la necesite, para no acumular
   * memoria en sesiones largas.
   */
  obtenerDocumentoUrl: async (empresaId, mensajeId) => {
    const token = getToken();
    const res = await fetch(`${API_URL}/empresas/${empresaId}/mensajes/${mensajeId}/documento`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      let detalle = `No se pudo cargar el documento (${res.status})`;
      try {
        const data = await res.json();
        detalle = data.detail || detalle;
      } catch (e) {
        // sin cuerpo JSON, se usa el detalle generico
      }
      throw new Error(detalle);
    }
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },
};
