const COLORES_TIPO = {
  "Orden de Pago": {
    badge: "bg-red-50 text-red-700 border border-red-200",
    punto: "bg-red-500",
  },
  "Resolución Coactiva": {
    badge: "bg-rose-50 text-rose-700 border border-rose-200",
    punto: "bg-rose-600",
  },
  "Resolución de Multa": {
    badge: "bg-orange-50 text-orange-700 border border-orange-200",
    punto: "bg-orange-500",
  },
  "Resolución de Determinación": {
    badge: "bg-amber-50 text-amber-700 border border-amber-200",
    punto: "bg-amber-500",
  },
  "Resolución de Intendencia": {
    badge: "bg-purple-50 text-purple-700 border border-purple-200",
    punto: "bg-purple-500",
  },
  "Resolución de Reclamación": {
    badge: "bg-indigo-50 text-indigo-700 border border-indigo-200",
    punto: "bg-indigo-500",
  },
  Esquela: {
    badge: "bg-yellow-50 text-yellow-700 border border-yellow-200",
    punto: "bg-yellow-500",
  },
  Requerimiento: {
    badge: "bg-cyan-50 text-cyan-700 border border-cyan-200",
    punto: "bg-cyan-500",
  },
  "Carta Inductiva": {
    badge: "bg-teal-50 text-teal-700 border border-teal-200",
    punto: "bg-teal-500",
  },
  Comunicación: {
    badge: "bg-sky-50 text-sky-700 border border-sky-200",
    punto: "bg-sky-500",
  },
  Otros: {
    badge: "bg-slate-100 text-slate-600 border border-slate-200",
    punto: "bg-slate-400",
  },
};

const POR_DEFECTO = COLORES_TIPO.Otros;

export function colorBadgeTipo(tipo) {
  return (COLORES_TIPO[tipo] || POR_DEFECTO).badge;
}

export function colorPuntoTipo(tipo) {
  return (COLORES_TIPO[tipo] || POR_DEFECTO).punto;
}
