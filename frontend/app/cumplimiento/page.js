"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Sidebar from "../../components/Sidebar";
import { getToken } from "../../lib/api";
import PanelSire from "./PanelSire";
import PanelDeudas from "./PanelDeudas";

const SUBMODULOS = [
  { id: "sire", label: "SIRE (Registros Electronicos)", activo: true },
  { id: "deudas", label: "Deudas (valores pendientes)", activo: true },
  { id: "dj", label: "Declaracion mensual", activo: false },
];

const CLAVE_PESTANA = "cumplimiento:pestana";

export default function CumplimientoPage() {
  const router = useRouter();
  const [pestana, setPestana] = useState(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    let guardada = null;
    try {
      guardada = localStorage.getItem(CLAVE_PESTANA);
    } catch {}
    setPestana(SUBMODULOS.some((s) => s.activo && s.id === guardada) ? guardada : "sire");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function elegir(id) {
    setPestana(id);
    try {
      localStorage.setItem(CLAVE_PESTANA, id);
    } catch {}
  }

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 pb-8 pt-24 xl:px-12">
        <h1 className="text-2xl font-extrabold tracking-tight text-ink">Cumplimiento</h1>
        <p className="mt-1 text-sm text-slate-600">
          Control de cumplimiento de cada empresa activa en SUNAT, leido directamente de SUNAT SOL
        </p>

        <div className="mt-5 flex gap-1 border-b border-slate-200">
          {SUBMODULOS.map((s) =>
            s.activo ? (
              <button
                key={s.id}
                onClick={() => elegir(s.id)}
                className={`border-b-2 px-4 py-2.5 text-sm font-semibold transition-colors ${
                  pestana === s.id ? "border-accent text-accent" : "border-transparent text-slate-500 hover:text-ink"
                }`}
              >
                {s.label}
              </button>
            ) : (
              <span
                key={s.id}
                title="Proximamente"
                className="cursor-not-allowed border-b-2 border-transparent px-4 py-2.5 text-sm font-semibold text-slate-400"
              >
                {s.label}
                <span className="ml-1.5 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-slate-500">Pronto</span>
              </span>
            )
          )}
        </div>

        {pestana === "sire" && <PanelSire />}
        {pestana === "deudas" && <PanelDeudas />}
      </main>
    </div>
  );
}
