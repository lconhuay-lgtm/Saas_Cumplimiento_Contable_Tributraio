// Compartido por las pestanas de Cumplimiento.

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
