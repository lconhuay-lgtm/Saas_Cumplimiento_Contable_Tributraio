"use client";

// Filtro por ultimo digito del RUC, compartido por SIRE, Declaracion mensual y
// Deudas: el cronograma de SUNAT vence por ultimo digito, asi que es la forma
// natural de revisar "las que vencen hoy". Se pueden marcar varios digitos.
const DIGITOS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

export function coincideDigitoRuc(ruc, digitos) {
  return !digitos.length || digitos.includes(String(ruc || "").slice(-1));
}

export default function FiltroDigitoRuc({ digitos, onCambio }) {
  function alternar(d) {
    onCambio(digitos.includes(d) ? digitos.filter((x) => x !== d) : [...digitos, d].sort());
  }
  const base = "h-7 min-w-[28px] rounded-md px-1.5 text-xs font-bold transition-colors";
  return (
    <div className="text-xs font-semibold text-slate-500">
      <span className="mr-2">Ultimo digito RUC</span>
      <span className="inline-flex flex-wrap items-center gap-1 align-middle">
        <button
          type="button"
          onClick={() => onCambio([])}
          className={`${base} ${!digitos.length ? "bg-accent text-white" : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-100"}`}
        >
          Todos
        </button>
        {DIGITOS.map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => alternar(d)}
            aria-pressed={digitos.includes(d)}
            className={`${base} ${
              digitos.includes(d) ? "bg-accent text-white" : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-100"
            }`}
          >
            {d}
          </button>
        ))}
      </span>
    </div>
  );
}
