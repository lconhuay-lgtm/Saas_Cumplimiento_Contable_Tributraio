"use client";
import { AlertCircle, DatabaseZap, Loader2 } from "lucide-react";
import { fechaHoraPeru } from "../../../../lib/fechas";
import { ESTADOS_LECTURA, ETAPAS_LECTURA, FUENTES_LECTURA, textoPeriodo, textoSoles } from "../../../../lib/liquidacion";

// Bloque 1 de la Liquidacion en vivo: lo leido de SUNAT para el periodo
// (0621, retenciones, percepciones, cuenta de control, Aduanas y SIRE), el
// avance de cada fuente y lo que quedo guardado. Solo lectura en SUNAT. El
// estado viene de useLecturas; el boton "Actualizar ahora" esta en el
// encabezado del tablero. Ademas se lee solo cada madrugada (backend:
// jobs_liquidacion.encolar_liquidacion_automatica).
function textoResumen(fuente, r) {
  if (!r) return "";
  switch (fuente) {
    case "declaraciones":
      return r.declaraciones.cantidad
        ? `${r.declaraciones.cantidad} periodos declarados · último: ${textoPeriodo(r.declaraciones.ultimo_periodo)}`
        : "Sin declaraciones guardadas";
    case "retenciones":
    case "percepciones":
      return `${r[fuente].cantidad} comprobante(s) del mes · ${textoSoles(r[fuente].monto)}`;
    case "aduanas":
      return `${r.aduanas.cantidad} liquidación(es) del mes · ${textoSoles(r.aduanas.monto)}`;
    case "cuenta_control":
      return r.cuenta_control.periodos
        ? `${r.cuenta_control.periodos} periodos · hasta ${textoPeriodo(r.cuenta_control.ultimo_periodo)}`
        : "Sin periodos guardados";
    case "sire":
      return `Ventas: ${r.ventas.cantidad} · IGV ${textoSoles(r.ventas.igv)} — Compras: ${r.compras.cantidad} · IGV ${textoSoles(r.compras.igv)}`;
    default:
      return "";
  }
}

export default function DatosSunatLiquidacion({ periodo, lecturas }) {
  const { datos, error } = lecturas;
  const porFuente = Object.fromEntries((datos?.lecturas || []).map((l) => [l.fuente, l]));

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <h3 className="flex items-center gap-2 font-heading text-lg font-bold text-ink">
        <DatabaseZap size={17} strokeWidth={1.75} className="text-accent" />
        Datos de SUNAT de {textoPeriodo(periodo)}
        {datos?.en_curso && <Loader2 size={15} className="animate-spin text-accent" />}
      </h3>
      <p className="mt-2 text-sm text-slate-600">
        Se leen solos cada madrugada a las 3:00 a.m.: el SIRE y Aduanas todos los días; las retenciones, percepciones y el
        0621, los lunes y jueves y a diario desde 5 días hábiles antes del vencimiento. «Actualizar ahora» lee todo en el
        momento (unos 10 minutos; puedes salir de la página).
      </p>

      {error && <div className="mt-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>}

      {!datos ? (
        !error && <p className="mt-4 text-sm text-slate-500">Cargando...</p>
      ) : (
        <ul className="mt-4 grid gap-x-8 divide-y divide-slate-100 lg:grid-cols-2 lg:divide-y-0">
          {FUENTES_LECTURA.map((f) => {
            const lectura = porFuente[f.id];
            const estado = lectura ? ESTADOS_LECTURA[lectura.estado] || ESTADOS_LECTURA.pendiente : null;
            return (
              <li key={f.id} className="py-3 lg:border-b lg:border-slate-100">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-ink">{f.texto}</div>
                    <div className="text-xs text-slate-500">{f.detalle}</div>
                  </div>
                  <div className="text-right">
                    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${estado ? estado.chip : "bg-slate-50 text-slate-400"}`}>
                      {lectura?.estado === "en_progreso" && lectura.etapa
                        ? ETAPAS_LECTURA[lectura.etapa] || estado.texto
                        : estado?.texto || "Sin leer"}
                    </span>
                    {lectura?.finalizado_en && (
                      <div className="mt-0.5 text-xs text-slate-400">{fechaHoraPeru(lectura.finalizado_en)}</div>
                    )}
                  </div>
                </div>
                <div className="mt-1 text-sm text-slate-700">{textoResumen(f.id, datos.resumen)}</div>
                {lectura?.estado === "error" && lectura.error && (
                  <div className="mt-1 flex items-start gap-1.5 text-xs text-red-600">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {lectura.error}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
