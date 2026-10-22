import { hoyPeru } from "../../lib/fechas";
// Compartido por las pestanas de Cumplimiento.

// Periodo que se muestra al entrar a SIRE y Declaracion mensual: el de
// vencimiento mas cercano, es decir el mes pasado (en octubre se declara y
// vence septiembre). Asi lo primero que se ve es lo que hay que cumplir ahora.
export function periodoPorDefecto() {
  const { anio, mes } = hoyPeru();
  return mes === 1 ? { anio: anio - 1, mes: 12 } : { anio, mes: mes - 1 };
}

// CSV con ";" y BOM UTF-8: Excel en espanol lo abre con columnas y tildes bien.
export function descargarCsv(nombreArchivo, encabezado, lineas) {
  const csv = [encabezado, ...lineas]
    .map((fila) => fila.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(";"))
    .join("\r\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = nombreArchivo;
  a.click();
  URL.revokeObjectURL(url);
}
