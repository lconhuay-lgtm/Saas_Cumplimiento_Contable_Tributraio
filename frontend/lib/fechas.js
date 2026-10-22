// Hora de Peru en el navegador, sin importar la zona horaria de la PC: el
// "hoy", el mes en curso y las horas que se muestran son siempre las de Lima.
// (Las FECHAS de vencimiento llegan como 00:00 UTC del dia y se muestran con
// timeZone "UTC" -- eso no cambia; esto es para el "hoy" y los instantes.)
export const ZONA_PERU = "America/Lima";

/** "2026-10-21" -- el dia de hoy (o de `momento`) en Peru. */
export function hoyPeruIso(momento = new Date()) {
  return momento.toLocaleDateString("en-CA", { timeZone: ZONA_PERU });
}

/** { anio, mes, dia } de hoy en Peru (mes 1-12). */
export function hoyPeru() {
  const [anio, mes, dia] = hoyPeruIso().split("-").map(Number);
  return { anio, mes, dia };
}

/** Instante (ms) en que empezo hoy en Peru (Peru es UTC-5 todo el anio). */
export function inicioDeHoyPeruMs() {
  return Date.parse(`${hoyPeruIso()}T00:00:00-05:00`);
}

/** Fecha de un instante, en hora de Peru: "21/10/2026". */
export function fechaPeru(valor, opciones = {}) {
  return new Date(valor).toLocaleDateString("es-PE", { timeZone: ZONA_PERU, ...opciones });
}

/** Fecha y hora de un instante, en hora de Peru: "21/10/2026, 9:15:00 p. m.". */
export function fechaHoraPeru(valor, opciones = {}) {
  return new Date(valor).toLocaleString("es-PE", { timeZone: ZONA_PERU, ...opciones });
}
