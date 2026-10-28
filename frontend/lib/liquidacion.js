// Textos compartidos de la Liquidacion en vivo (pestana de Cumplimiento y
// pestana dentro de cada empresa). Los estados vienen del backend
// (routers/liquidacion.py::_estado), en orden de lo que falta hacer.

export const ESTADOS_LIQUIDACION = {
  no_activada: {
    texto: "No activada",
    chip: "bg-slate-100 text-slate-500",
    siguiente: "Un administrador debe activar la Liquidación en vivo para esta empresa.",
  },
  falta_responsable: {
    texto: "Falta responsable",
    chip: "bg-amber-50 text-amber-700",
    siguiente: "Asigna un responsable en la pestaña Configuración de la empresa: es quien guarda las credenciales de la API.",
  },
  falta_api: {
    texto: "Falta API del SIRE",
    chip: "bg-amber-50 text-amber-700",
    siguiente: "El responsable debe guardar el ID y la clave de la API del SIRE (ver la guía).",
  },
  sin_probar: {
    texto: "Sin probar",
    chip: "bg-sky-50 text-sky-700",
    siguiente: "Credenciales guardadas. Usa \"Probar conexión\" para confirmar que funcionan.",
  },
  api_error: {
    texto: "Error de conexión",
    chip: "bg-red-50 text-red-700",
    siguiente: "La última prueba falló. Revisa el mensaje y corrige las credenciales.",
  },
  no_afiliada: {
    texto: "No afiliada al SIRE",
    chip: "bg-red-50 text-red-700",
    siguiente: "No afiliada al SIRE: no se puede calcular la liquidación en vivo.",
  },
  lista: {
    texto: "Lista",
    chip: "bg-emerald-50 text-emerald-700",
    siguiente: "Todo configurado. El cálculo diario empieza cuando se publique la siguiente etapa.",
  },
};

export const REGIMENES = [
  { id: "general", texto: "Régimen General" },
  { id: "mype", texto: "MYPE Tributario" },
  { id: "especial", texto: "Régimen Especial (RER)" },
  { id: "agrario", texto: "Régimen Agrario" },
  { id: "amazonia", texto: "Amazonía" },
];

export function textoRegimen(id) {
  return REGIMENES.find((r) => r.id === id)?.texto || "Sin definir";
}

export const ACCIONES_EVENTO = {
  activada: "Activó la Liquidación en vivo",
  desactivada: "Desactivó la Liquidación en vivo",
  api_guardada: "Guardó las credenciales de la API del SIRE",
  api_borrada: "Borró las credenciales de la API del SIRE",
  conexion_probada: "Probó la conexión",
  regimen_cambiado: "Cambió el régimen",
  lectura_solicitada: "Pidió leer los datos de SUNAT del periodo",
};

// Fuentes que lee el Bloque 1 (backend/app/jobs_liquidacion.py), en el orden en que se leen.
export const FUENTES_LECTURA = [
  { id: "declaraciones", texto: "Declaraciones 0621", detalle: "Casillas de cada 0621 presentado (historial)" },
  { id: "retenciones", texto: "Retenciones recibidas", detalle: "Comprobantes de retención del mes" },
  { id: "percepciones", texto: "Percepciones recibidas", detalle: "Comprobantes de percepción del mes" },
  { id: "cuenta_control", texto: "Cuenta de control", detalle: "Retenciones y percepciones de los periodos declarados" },
  { id: "aduanas", texto: "Percepciones de importación", detalle: "Liquidaciones de cobranza de Aduanas" },
  { id: "sire", texto: "Ventas y compras (SIRE)", detalle: "Propuesta del SIRE del mes" },
];

export const ESTADOS_LECTURA = {
  pendiente: { texto: "En cola", chip: "bg-slate-100 text-slate-600" },
  en_progreso: { texto: "Leyendo", chip: "bg-sky-50 text-sky-700" },
  completado: { texto: "Leído", chip: "bg-emerald-50 text-emerald-700" },
  error: { texto: "Error", chip: "bg-red-50 text-red-700" },
};

export const ETAPAS_LECTURA = {
  iniciando_sesion: "Entrando a SUNAT",
  autenticando: "Entrando con la clave SOL",
  abriendo_declaraciones: "Abriendo Mis Declaraciones",
  leyendo_declaraciones: "Leyendo los 0621",
  leyendo_retenciones: "Leyendo retenciones",
  leyendo_percepciones: "Leyendo percepciones",
  leyendo_cuenta_control: "Leyendo la cuenta de control",
  esperando_turno_sire: "Esperando turno del SIRE",
  leyendo_ventas: "Leyendo ventas",
  leyendo_compras: "Leyendo compras",
};

const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "setiembre", "octubre", "noviembre", "diciembre"];

/** "2026-10" -> "octubre 2026" */
export function textoPeriodo(periodo) {
  if (!periodo) return "";
  const [anio, mes] = periodo.split("-").map(Number);
  return `${MESES[mes - 1]} ${anio}`;
}
