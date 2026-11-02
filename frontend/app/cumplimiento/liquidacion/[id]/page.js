"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, ChevronRight, Settings2 } from "lucide-react";
import Sidebar from "../../../../components/Sidebar";
import { api, getToken } from "../../../../lib/api";
import { periodosElegibles, textoRegimen } from "../../../../lib/liquidacion";
import DatosSunatLiquidacion from "./DatosSunatLiquidacion";
import TableroLiquidacion from "./TableroLiquidacion";

// Tablero de la Liquidacion en vivo de una empresa, dentro de Cumplimiento como
// en el boceto (Cumplimiento › Liquidacion en vivo › empresa): el estimado del
// periodo y los datos leidos de SUNAT. Se abre desde "Liquidacion del mes"; la
// configuracion (API del SIRE y regimen) sigue en la pestana de la empresa.
const PANEL = "/cumplimiento?tab=liquidacion";
const BOTON =
  "inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-semibold text-slate-600 shadow-sm transition-colors hover:border-accent hover:text-accent";

export default function TableroEmpresaPage() {
  const { id } = useParams();
  const router = useRouter();
  const [{ lista: periodos, porDefecto }] = useState(periodosElegibles);
  const [periodo, setPeriodo] = useState(porDefecto);
  const [version, setVersion] = useState(0); // sube al terminar una lectura: el tablero recalcula
  const [empresa, setEmpresa] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api.obtenerLiquidacionEmpresa(id).then(setEmpresa).catch((err) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 pb-8 pt-24 xl:px-12">
        <nav className="flex flex-wrap items-center gap-1 text-sm text-slate-500">
          <Link href={PANEL} className="hover:text-accent">Cumplimiento</Link>
          <ChevronRight size={14} />
          <Link href={PANEL} className="hover:text-accent">Liquidación en vivo</Link>
          <ChevronRight size={14} />
          <span className="font-semibold text-ink">{empresa?.razon_social || "..."}</span>
        </nav>

        <div className="mt-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-ink">{empresa?.razon_social || "Liquidación en vivo"}</h1>
            {empresa && (
              <p className="mt-1 text-sm text-slate-500">
                RUC {empresa.ruc} · {empresa.regimen ? textoRegimen(empresa.regimen) : "Régimen sin definir"} ·{" "}
                {empresa.responsable_nombre ? `Responsable: ${empresa.responsable_nombre}` : "Sin responsable asignado"}
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href={`/empresas/${id}?tab=liquidacion`} className={BOTON}>
              <Settings2 size={15} strokeWidth={1.75} />
              Configuración
            </Link>
            <Link href={PANEL} className={BOTON}>
              <ArrowLeft size={15} strokeWidth={1.5} />
              Volver al panel
            </Link>
          </div>
        </div>

        {error && <div className="mt-6 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>}
        {!empresa && !error && <p className="mt-8 text-sm text-slate-500">Cargando...</p>}

        {empresa && !empresa.activa && (
          <div className="mt-6 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2.5 text-sm text-amber-800">
            La Liquidación en vivo no está activada para esta empresa. Un administrador la activa en la vista «Configuración»
            del panel.
          </div>
        )}

        {empresa?.activa && (
          <div className="mt-6 space-y-5">
            <TableroLiquidacion empresaId={id} periodo={periodo} periodos={periodos} onPeriodo={setPeriodo} version={version} />
            <DatosSunatLiquidacion empresaId={id} periodo={periodo} onLeido={() => setVersion((v) => v + 1)} />
          </div>
        )}
      </main>
    </div>
  );
}
