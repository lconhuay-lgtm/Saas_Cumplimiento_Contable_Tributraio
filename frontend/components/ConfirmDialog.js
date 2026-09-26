"use client";

// Modal de confirmacion generico, con el mismo patron visual que ya usaban
// ModalElegirTipoFichaRuc y ModalReporteTributario en empresas/page.js
// (overlay bg-ink/60 + card rounded-2xl centrada) -- se extrajo aca para
// no repetir el mismo markup en cada pantalla que necesite reemplazar un
// window.confirm() nativo por uno estilizado.
export default function ConfirmDialog({
  titulo,
  mensaje,
  textoConfirmar = "Confirmar",
  textoCancelar = "Cancelar",
  peligroso = false,
  onConfirmar,
  onCancelar,
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-6" onClick={onCancelar}>
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-soft-lg" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-base font-bold text-ink">{titulo}</h3>
        {typeof mensaje === "string" ? <p className="mt-2 text-sm text-slate-600">{mensaje}</p> : mensaje}
        <div className="mt-5 flex flex-col gap-2">
          <button
            onClick={onConfirmar}
            className={`flex items-center justify-center gap-1.5 rounded-lg px-4 py-2.5 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 ${
              peligroso ? "bg-red-600 hover:bg-red-700" : "bg-violet-600 hover:bg-violet-700"
            }`}
          >
            {textoConfirmar}
          </button>
          <button
            onClick={onCancelar}
            className="mt-1 flex items-center justify-center rounded-lg px-4 py-2 text-xs font-medium text-slate-400 transition-colors duration-300 ease-out hover:text-slate-600"
          >
            {textoCancelar}
          </button>
        </div>
      </div>
    </div>
  );
}
