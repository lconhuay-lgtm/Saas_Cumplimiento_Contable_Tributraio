"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { BookOpen, Loader2, Search, Settings2 } from "lucide-react";
import { api } from "../../lib/api";
import { ESTADOS_LIQUIDACION, textoRegimen } from "../../lib/liquidacion";
import FiltroDigitoRuc, { coincideDigitoRuc } from "./FiltroDigitoRuc";

// Etapa 1 de la Liquidacion en vivo: activar empresas (solo admin) y ver que
// le falta a cada una para quedar lista (responsable, API del SIRE, prueba).
// El tablero con el IGV del mes se suma aca en las etapas siguientes.
export default function PanelLiquidacion() {
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [digitos, setDigitos] = useState([]);
  const [soloActivadas, setSoloActivadas] = useState(true);
  const [cambiando, setCambiando] = useState(null);

  useEffect(() => {
    cargar();
  }, []);

  async function cargar() {
    try {
      const data = await api.listarLiquidacion();
      setDatos(data);
      // Sin ninguna activada todavia, el admin necesita ver todas para elegir.
      if (!data.empresas.some((e) => e.activa)) setSoloActivadas(false);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setCargando(false);
    }
  }

  async function alternar(empresa) {
    setCambiando(empresa.empresa_id);
    try {
      await api.activarLiquidacion(empresa.empresa_id, !empresa.activa);
      await cargar();
    } catch (err) {
      setError(err.message);
    } finally {
      setCambiando(null);
    }
  }

  const visibles = useMemo(() => {
    if (!datos) return [];
    const q = busqueda.trim().toLowerCase();
    return datos.empresas.filter((e) => {
      if (soloActivadas && !e.activa) return false;
      if (!coincideDigitoRuc(e.ruc, digitos)) return false;
      if (q && !e.razon_social.toLowerCase().includes(q) && !e.ruc.includes(q)) return false;
      return true;
    });
  }, [datos, busqueda, digitos, soloActivadas]);

  const conteo = useMemo(() => {
    const c = {};
    (datos?.empresas || []).filter((e) => e.activa).forEach((e) => (c[e.estado] = (c[e.estado] || 0) + 1));
    return c;
  }, [datos]);

  if (cargando) return <p className="mt-8 text-sm text-slate-500">Cargando...</p>;

  const adicionales = datos ? Math.max(0, datos.activas - datos.incluidas) : 0;

  return (
    <>
      <div className="mt-5 flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-600">
          Cuánto IGV y Renta pagaría cada empresa si el mes cerrara hoy. En esta primera etapa se activan las empresas y se
          conecta la API del SIRE de cada una; el cálculo diario se suma en las etapas siguientes.
        </p>
        <Link
          href="/liquidacion/guia"
          target="_blank"
          className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-semibold text-slate-600 hover:border-accent hover:text-accent"
        >
          <BookOpen size={15} strokeWidth={1.75} />
          Guía: credenciales de la API del SIRE
        </Link>
      </div>

      {error && <div className="mt-4 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>}

      {datos && (
        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Tarjeta titulo="Empresas activadas" valor={`${datos.activas} de ${datos.incluidas} incluidas`}
            nota={adicionales ? `${adicionales} adicional(es) fuera del plan fijo` : "Dentro del plan fijo"} />
          <Tarjeta titulo="Listas" valor={conteo.lista || 0} nota="API conectada y afiliadas al SIRE" />
          <Tarjeta titulo="Por configurar" valor={(conteo.falta_api || 0) + (conteo.falta_responsable || 0) + (conteo.sin_probar || 0)}
            nota="Falta responsable, API o la prueba" />
          <Tarjeta titulo="Con problema" valor={(conteo.api_error || 0) + (conteo.no_afiliada || 0)}
            nota="Error de conexión o no afiliadas al SIRE" />
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <div className="relative">
          <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar por nombre o RUC"
            className="w-64 rounded-lg border border-slate-200 bg-white py-1.5 pl-8 pr-3 text-sm focus:border-accent focus:outline-none"
          />
        </div>
        <label className="flex items-center gap-2 text-sm font-medium text-slate-600">
          <input type="checkbox" checked={soloActivadas} onChange={(e) => setSoloActivadas(e.target.checked)} className="accent-accent" />
          Solo activadas
        </label>
        <FiltroDigitoRuc digitos={digitos} onCambio={setDigitos} />
      </div>

      <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Empresa</th>
              <th className="px-4 py-3">Responsable</th>
              <th className="px-4 py-3">Régimen</th>
              <th className="px-4 py-3">Situación</th>
              <th className="px-4 py-3 text-right">Acciones</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {visibles.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                  {soloActivadas
                    ? "Ninguna empresa activada con estos filtros. Desmarca \"Solo activadas\" para ver todas."
                    : "Ninguna empresa con estos filtros."}
                </td>
              </tr>
            )}
            {visibles.map((e) => {
              const estado = ESTADOS_LIQUIDACION[e.estado] || ESTADOS_LIQUIDACION.no_activada;
              return (
                <tr key={e.empresa_id} className="align-top">
                  <td className="px-4 py-3">
                    <Link href={`/empresas/${e.empresa_id}?tab=liquidacion`} className="font-semibold text-ink hover:text-accent">
                      {e.razon_social}
                    </Link>
                    <div className="text-xs text-slate-500">RUC {e.ruc}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{e.responsable_nombre || <span className="text-amber-600">Sin asignar</span>}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {e.regimen ? textoRegimen(e.regimen) : e.regimen_sugerido ? `${textoRegimen(e.regimen_sugerido)} (sugerido)` : "Sin definir"}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${estado.chip}`}>{estado.texto}</span>
                    {e.activa && e.estado !== "lista" && <div className="mt-1 max-w-xs text-xs text-slate-500">{estado.siguiente}</div>}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      {datos.es_admin && (
                        <button
                          onClick={() => alternar(e)}
                          disabled={cambiando === e.empresa_id}
                          className={`flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-bold transition-colors disabled:opacity-60 ${
                            e.activa ? "border border-slate-200 text-slate-600 hover:border-red-300 hover:text-red-600" : "bg-accent text-white hover:opacity-90"
                          }`}
                        >
                          {cambiando === e.empresa_id && <Loader2 size={13} className="animate-spin" />}
                          {e.activa ? "Desactivar" : "Activar"}
                        </button>
                      )}
                      {e.activa && (
                        <Link
                          href={`/empresas/${e.empresa_id}?tab=liquidacion`}
                          className="flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-600 hover:border-accent hover:text-accent"
                        >
                          <Settings2 size={13} strokeWidth={1.75} />
                          Configurar
                        </Link>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Tarjeta({ titulo, valor, nota }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{titulo}</div>
      <div className="mt-1 text-xl font-extrabold text-ink">{valor}</div>
      <div className="mt-0.5 text-xs text-slate-500">{nota}</div>
    </div>
  );
}
