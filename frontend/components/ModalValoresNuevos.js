"use client";

import { ArrowRight, Building2, Gavel, Landmark, X } from "lucide-react";

// Ventana emergente de "valores nuevos" (deudas que SUNAT empezo a mostrar en
// "Valores pendientes de pago") al entrar a la app -- mismo patron visual que
// ModalNotificacionesNuevas.js. Solo trae valores con notificado_popup=False
// (ver backend/app/routers/deudas.py); la primera lectura de cada empresa
// nunca llega hasta aca. Cada clic lleva a Cumplimiento > Deudas con la
// empresa abierta y el valor resaltado.
const soles = new Intl.NumberFormat("es-PE", { style: "currency", currency: "PEN" });

function fechaIso(valor) {
  if (!valor) return null;
  const [a, m, d] = valor.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

export default function ModalValoresNuevos({ grupos, onIrADeuda, onCerrar }) {
  const totalValores = grupos.reduce((acc, g) => acc + g.valores.length, 0);
  const totalSaldo = grupos.reduce((acc, g) => acc + g.valores.reduce((s, v) => s + v.saldo_total, 0), 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-6" onClick={onCerrar}>
      <div
        className="flex max-h-[80vh] w-full max-w-xl flex-col rounded-2xl bg-white shadow-soft-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-red-50 text-red-600">
              <Landmark size={18} strokeWidth={1.75} />
            </div>
            <div>
              <h3 className="text-base font-bold text-ink">Nuevas deudas en SUNAT</h3>
              <p className="text-xs text-slate-500">
                {totalValores} valor{totalValores === 1 ? "" : "es"} nuevo{totalValores === 1 ? "" : "s"} en{" "}
                {grupos.length} empresa{grupos.length === 1 ? "" : "s"} · {soles.format(totalSaldo)}
              </p>
            </div>
          </div>
          <button
            onClick={onCerrar}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Cerrar"
          >
            <X size={15} strokeWidth={1.75} />
          </button>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto px-6 py-4">
          {grupos.map((grupo) => (
            <div key={grupo.empresa_id} className="rounded-xl border border-slate-100 p-4">
              <div className="flex items-center gap-2">
                <Building2 size={14} strokeWidth={1.75} className="shrink-0 text-slate-400" />
                <span className="truncate text-sm font-semibold text-ink" title={grupo.razon_social}>
                  {grupo.razon_social}
                </span>
                <span className="shrink-0 text-xs text-slate-400">{grupo.ruc}</span>
              </div>
              <ul className="mt-2 space-y-1.5">
                {grupo.valores.map((v) => (
                  <li key={v.id}>
                    <button
                      onClick={() => onIrADeuda(grupo, [v])}
                      className="flex w-full items-start justify-between gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-slate-50"
                      title="Ver el detalle de esta deuda"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-xs font-semibold text-ink">
                          {v.tipo_descripcion || "Valor"} {v.num_valor}
                          {v.reaparecio && <span className="ml-1.5 font-medium text-amber-600">(volvio a aparecer)</span>}
                        </span>
                        <span className="block truncate text-[11px] text-slate-500">
                          Periodo {v.periodo} · {v.tributo}
                          {fechaIso(v.fecha_notificacion) ? ` · notificado ${fechaIso(v.fecha_notificacion)}` : ""}
                        </span>
                        {v.en_cobranza_coactiva && (
                          <span className="mt-0.5 inline-flex items-center gap-1 rounded-full bg-red-50 px-1.5 py-0.5 text-[10px] font-bold text-red-700">
                            <Gavel size={10} strokeWidth={2} />
                            {v.etapa || "En cobranza coactiva"}
                          </span>
                        )}
                      </span>
                      <span className="shrink-0 text-sm font-bold text-ink">{soles.format(v.saldo_total)}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <button
                onClick={() => onIrADeuda(grupo, grupo.valores)}
                className="mt-3 flex items-center gap-1 text-xs font-semibold text-accent hover:underline"
              >
                Ver las deudas de esta empresa
                <ArrowRight size={12} strokeWidth={2} />
              </button>
            </div>
          ))}
        </div>

        <div className="border-t border-slate-100 px-6 py-4">
          <button
            onClick={onCerrar}
            className="flex w-full items-center justify-center rounded-lg px-4 py-2.5 text-sm font-semibold text-slate-500 transition-colors duration-300 ease-out hover:bg-slate-50 hover:text-slate-700"
          >
            Entendido
          </button>
        </div>
      </div>
    </div>
  );
}
