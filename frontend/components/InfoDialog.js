"use client";
import { CheckCircle2, AlertTriangle, Info } from "lucide-react";

// Modal informativo de un solo boton ("Aceptar"), mismo patron visual que
// ConfirmDialog -- pensado para reemplazar los alert() nativos que solo
// avisan un resultado (no piden confirmacion), como el de "no hay mensajes
// nuevos" de una consulta individual o el resumen final de una Consulta
// masiva (ver empresas/page.js y dashboard/page.js).
const ESTILOS_VARIANTE = {
  ok: { Icon: CheckCircle2, color: "bg-emerald-100 text-emerald-600" },
  error: { Icon: AlertTriangle, color: "bg-red-100 text-red-600" },
  info: { Icon: Info, color: "bg-accent-light text-accent" },
};

export default function InfoDialog({ titulo, mensaje, variante = "info", textoAceptar = "Aceptar", onCerrar }) {
  const { Icon, color } = ESTILOS_VARIANTE[variante] || ESTILOS_VARIANTE.info;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-6" onClick={onCerrar}>
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-soft-lg" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start gap-3">
          <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${color}`}>
            <Icon size={18} strokeWidth={2} />
          </span>
          <div className="min-w-0">
            <h3 className="text-base font-bold text-ink">{titulo}</h3>
            {typeof mensaje === "string" ? (
              <p className="mt-1.5 whitespace-pre-line text-sm text-slate-600">{mensaje}</p>
            ) : (
              <div className="mt-1.5 text-sm text-slate-600">{mensaje}</div>
            )}
          </div>
        </div>
        <button
          onClick={onCerrar}
          className="mt-5 flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark"
        >
          {textoAceptar}
        </button>
      </div>
    </div>
  );
}
