// Etapas que reporta el backend durante cada tipo de trabajo en vivo
// (consulta al buzon, Ficha RUC, Reporte Tributario). El porcentaje es una
// estimacion fija por etapa (no hay forma de medir tiempo real dentro de
// una sesion de Selenium), pero le da al usuario una idea de cuanto falta
// en vez de un spinner sin contexto. Vive en un modulo propio (no dentro de
// empresas/page.js) porque tanto esa pantalla como el indicador global de
// TrabajosContext necesitan la misma tabla.

const ETAPAS_FICHA_RUC = {
  null: { porcentaje: 8, etiqueta: "Iniciando..." },
  iniciando_sesion: { porcentaje: 20, etiqueta: "Abriendo SUNAT..." },
  autenticando: { porcentaje: 40, etiqueta: "Iniciando sesion..." },
  abriendo_ficha: { porcentaje: 60, etiqueta: "Abriendo la Ficha RUC..." },
  generando_pdf: { porcentaje: 85, etiqueta: "Generando el PDF..." },
  guardando: { porcentaje: 95, etiqueta: "Guardando..." },
};

const ETAPAS_REPORTE_TRIBUTARIO = {
  null: { porcentaje: 8, etiqueta: "Iniciando..." },
  iniciando_sesion: { porcentaje: 20, etiqueta: "Abriendo SUNAT..." },
  autenticando: { porcentaje: 35, etiqueta: "Iniciando sesion..." },
  abriendo_reporte: { porcentaje: 55, etiqueta: "Abriendo el Reporte Tributario..." },
  aceptando_aviso: { porcentaje: 70, etiqueta: "Aceptando el aviso legal..." },
  enviando_correo: { porcentaje: 90, etiqueta: "Enviando la solicitud..." },
};

const ETAPAS_CONSULTA = {
  null: { porcentaje: 5, etiqueta: "Iniciando..." },
  iniciando_sesion: { porcentaje: 15, etiqueta: "Abriendo SUNAT..." },
  autenticando: { porcentaje: 30, etiqueta: "Iniciando sesion..." },
  leyendo_estado: { porcentaje: 50, etiqueta: "Leyendo estado del contribuyente..." },
  abriendo_buzon: { porcentaje: 65, etiqueta: "Abriendo el buzon..." },
  leyendo_mensajes: { porcentaje: 75, etiqueta: "Leyendo mensajes..." },
  descargando_documentos: { porcentaje: 85, etiqueta: "Descargando documentos nuevos..." },
  leyendo_buzon_mensajes: { porcentaje: 95, etiqueta: "Leyendo Buzón Mensajes..." },
};

const TABLAS_POR_TIPO = {
  ficha: ETAPAS_FICHA_RUC,
  reporte: ETAPAS_REPORTE_TRIBUTARIO,
  consulta: ETAPAS_CONSULTA,
};

export const TITULO_TIPO_TRABAJO = {
  ficha: "Generando Ficha RUC",
  reporte: "Solicitando Reporte Tributario",
  consulta: "Consultando el buzon",
};

export function infoEtapa(tipo, etapa) {
  const tabla = TABLAS_POR_TIPO[tipo] || ETAPAS_CONSULTA;
  return tabla[etapa || "null"] || tabla.null;
}

export function infoEtapaFichaRuc(etapa) {
  return infoEtapa("ficha", etapa);
}

export function infoEtapaReporteTributario(etapa) {
  return infoEtapa("reporte", etapa);
}

export function infoEtapaConsulta(etapa) {
  return infoEtapa("consulta", etapa);
}
