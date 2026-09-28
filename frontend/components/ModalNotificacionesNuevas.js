"use client";

import { BellRing, Building2, ArrowRight, X } from "lucide-react";

// Ventana emergente de "mensajes nuevos" al entrar a la app -- mismo patron
// visual que ConfirmDialog.js / los modales de empresas/page.js (overlay
// bg-ink/60 + card rounded-2xl centrada). Solo se muestra cuando hay
// mensajes con notificado_popup=False (ver backend/app/routers/notificaciones.py)
// -- el backlog del alta inicial de una empresa nunca llega hasta aca.
const MAX_ASUNTOS_VISIBLES = 5;

export default function ModalNotificacionesNuevas({ grupos, onIrAEmpresa, onCerrar }) {
  const totalMensajes = grupos.reduce((acc, g) => acc + g.mensajes.length, 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-6" onClick={onCerrar}>
      <div
        className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-2xl bg-white shadow-soft-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-light text-accent">
              <BellRing size={18} strokeWidth={1.75} />
            </div>
            <div>
              <h3 className="text-base font-bold text-ink">Mensajes nuevos en el buzon</h3>
              <p className="text-xs text-slate-500">
                {totalMensajes} mensaje{totalMensajes === 1 ? "" : "s"} en {grupos.length} empresa
                {grupos.length === 1 ? "" : "s"}
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
          {grupos.map((grupo) => {
            const visibles = grupo.mensajes.slice(0, MAX_ASUNTOS_VISIBLES);
            const restantes = grupo.mensajes.length - visibles.length;
            return (
              <div key={grupo.empresa_id} className="rounded-xl border border-slate-100 p-4">
                <div className="flex items-center gap-2">
                  <Building2 size={14} strokeWidth={1.75} className="shrink-0 text-slate-400" />
                  <span className="truncate text-sm font-semibold text-ink" title={grupo.razon_social}>
                    {grupo.razon_social}
                  </span>
                  <span className="shrink-0 text-xs text-slate-400">{grupo.ruc}</span>
                  <span className="ml-auto shrink-0 rounded-full bg-accent-light px-2 py-0.5 text-[11px] font-semibold text-accent-dark">
                    {grupo.mensajes.length}
                  </span>
                </div>
                <ul className="mt-2 space-y-1">
                  {visibles.map((m) => (
                    <li key={m.id} className="truncate text-xs text-slate-600" title={m.asunto}>
                      &middot; {m.asunto}
                    </li>
                  ))}
                  {restantes > 0 && <li className="text-xs text-slate-400">y {restantes} mas...</li>}
                </ul>
                <button
                  onClick={() => onIrAEmpresa(grupo)}
                  className="mt-3 flex items-center gap-1 text-xs font-semibold text-accent hover:underline"
                >
                  Ver en el buzon
                  <ArrowRight size={12} strokeWidth={2} />
                </button>
              </div>
            );
          })}
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
