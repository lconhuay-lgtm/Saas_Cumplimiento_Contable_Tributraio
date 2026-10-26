"use client";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Sidebar from "../../components/Sidebar";
import { getToken } from "../../lib/api";
import PanelSire from "./PanelSire";
import PanelDeudas from "./PanelDeudas";
import PanelDeclaraciones from "./PanelDeclaraciones";
import PanelDetracciones from "./PanelDetracciones";
import PanelLiquidacion from "./PanelLiquidacion";

const SUBMODULOS = [
  { id: "liquidacion", label: "Liquidación en vivo", activo: true },
  { id: "sire", label: "SIRE (Registros Electronicos)", activo: true },
  { id: "dj", label: "Declaracion mensual", activo: true },
  { id: "deudas", label: "Deudas (valores pendientes)", activo: true },
  { id: "detracciones", label: "Detracciones", activo: true },
];

const CLAVE_PESTANA = "cumplimiento:pestana";

// useSearchParams() exige un limite de Suspense en el build (mismo motivo que empresas/page.js).
export default function CumplimientoPage() {
  return (
    <Suspense fallback={null}>
      <CumplimientoContenido />
    </Suspense>
  );
}

function CumplimientoContenido() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [pestana, setPestana] = useState(null);

  // ?tab=deudas&empresa=<id>&valores=<nro,nro> -- llega desde la ventana de
  // "Nuevas deudas en SUNAT" (ModalValoresNuevos.js) para abrir esa deuda.
  const tabPedida = searchParams.get("tab");
  const empresaEnfocada = searchParams.get("empresa");
  const valoresEnfocados = searchParams.get("valores") || "";
  const enfoque = useMemo(
    () => (empresaEnfocada ? { empresaId: empresaEnfocada, valores: valoresEnfocados.split(",").filter(Boolean) } : null),
    [empresaEnfocada, valoresEnfocados]
  );

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    if (SUBMODULOS.some((s) => s.activo && s.id === tabPedida)) {
      setPestana(tabPedida);
      return;
    }
    let guardada = null;
    try {
      guardada = localStorage.getItem(CLAVE_PESTANA);
    } catch {}
    setPestana(SUBMODULOS.some((s) => s.activo && s.id === guardada) ? guardada : "liquidacion");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabPedida, empresaEnfocada, valoresEnfocados]);

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

        {pestana === "liquidacion" && <PanelLiquidacion />}
        {pestana === "sire" && <PanelSire />}
        {pestana === "dj" && <PanelDeclaraciones />}
        {pestana === "deudas" && <PanelDeudas enfoque={enfoque} />}
        {pestana === "detracciones" && <PanelDetracciones empresaInicial={empresaEnfocada} />}
      </main>
    </div>
  );
}
