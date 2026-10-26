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
};
