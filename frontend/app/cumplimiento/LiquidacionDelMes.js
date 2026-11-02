"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Search } from "lucide-react";
import { api } from "../../lib/api";
import { fechaHoraPeru, fechaPeru, hoyPeruIso } from "../../lib/fechas";
import { periodosElegibles, textoPeriodo, textoRegimen, textoSoles } from "../../lib/liquidacion";
import FiltroDigitoRuc, { coincideDigitoRuc } from "./FiltroDigitoRuc";

// Bloque 2 de la Liquidacion en vivo: el estimado del periodo de cada empresa
// activada, ordenado por vencimiento (parametros 4.5 y 4.7). Clic en una
// empresa abre su tablero (cumplimiento/liquidacion/[id]).
function textoVence(vence) {
  if (!vence) return { texto: "—", nota: "", urgente: false };
  const dias = Math.round((Date.parse(vence) - Date.parse(hoyPeruIso())) / 86400000);
  return {
    texto: fechaPeru(vence, { timeZone: "UTC", day: "2-digit", month: "2-digit" }),
    nota: dias < 0 ? "vencido" : dias === 0 ? "hoy" : `en ${dias} día${dias === 1 ? "" : "s"}`,
    urgente: dias <= 3,
  };
}

export default function LiquidacionDelMes() {
  const [{ lista, porDefecto }] = useState(periodosElegibles);
  const [periodo, setPeriodo] = useState(porDefecto);
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [digitos, setDigitos] = useState([]);

  useEffect(() => {
    let vigente = true;
    setDatos(null);
    api.verPanelLiquidacion(periodo)
      .then((data) => vigente && (setDatos(data), setError("")))
      .catch((err) => vigente && setError(err.message));
    return () => {
      vigente = false;
    };
  }, [periodo]);

  const visibles = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    return (datos?.empresas || []).filter(
      (e) => coincideDigitoRuc(e.ruc, digitos) && (!q || e.razon_social.toLowerCase().includes(q) || e.ruc.includes(q)),
    );
  }, [datos, busqueda, digitos]);

  const totales = useMemo(() => {
    const t = { igv: 0, renta: 0, sinDatos: 0 };
    visibles.forEach((e) => {
      if (!e.hay_datos) t.sinDatos += 1;
      else if (!e.declarado) {
        t.igv += e.igv_por_pagar;
        t.renta += e.renta_por_pagar || 0;
      }
    });
    return t;
  }, [visibles]);

  return (
    <>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <select
          value={periodo}
          onChange={(e) => setPeriodo(e.target.value)}
          className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm capitalize focus:border-accent focus:outline-none"
        >
          {lista.map((p) => (
            <option key={p} value={p}>{textoPeriodo(p)}</option>
          ))}
        </select>
        <div className="relative">
          <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar por nombre o RUC"
            className="w-64 rounded-lg border border-slate-200 bg-white py-1.5 pl-8 pr-3 text-sm focus:border-accent focus:outline-none"
          />
        </div>
        <FiltroDigitoRuc digitos={digitos} onCambio={setDigitos} />
      </div>

      {error && <div className="mt-4 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>}

      {datos && (
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <Tarjeta titulo="IGV por pagar" valor={textoSoles(totales.igv)} nota="Suma de las que aún no declaran" />
          <Tarjeta titulo="Renta por pagar" valor={textoSoles(totales.renta)} nota="Suma de las que aún no declaran" />
          <Tarjeta titulo="Sin datos del mes" valor={totales.sinDatos} nota="Falta leer el SIRE del periodo" />
        </div>
      )}

      <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Empresa</th>
              <th className="px-4 py-3">Vence</th>
              <th className="px-4 py-3 text-right">IGV</th>
              <th className="px-4 py-3 text-right">Renta</th>
              <th className="px-4 py-3">Situación</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {!datos && !error && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500">Calculando...</td>
              </tr>
            )}
            {datos && visibles.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                  Ninguna empresa activada con estos filtros. Actívalas en la vista «Configuración».
                </td>
              </tr>
            )}
            {visibles.map((e) => {
              const vence = textoVence(e.vence);
              return (
                <tr key={e.empresa_id} className="align-top">
                  <td className="px-4 py-3">
                    <Link href={`/cumplimiento/liquidacion/${e.empresa_id}`} className="font-semibold text-ink hover:text-accent">
                      {e.razon_social}
                    </Link>
                    <div className="text-xs text-slate-500">
                      RUC {e.ruc} · {textoRegimen(e.regimen)}{e.responsable_nombre ? ` · ${e.responsable_nombre}` : ""}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <div className="font-semibold text-ink">{vence.texto}</div>
                    <div className={`text-xs ${vence.urgente && !e.declarado ? "font-semibold text-red-600" : "text-slate-500"}`}>{vence.nota}</div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                    {!e.hay_datos ? (
                      <span className="text-slate-400">—</span>
                    ) : e.saldo_a_favor ? (
                      <>
                        <div className="font-semibold text-emerald-700">{textoSoles(e.saldo_a_favor)}</div>
                        <div className="text-xs text-slate-500">saldo a favor</div>
                      </>
                    ) : (
                      <div className="font-semibold text-ink">{textoSoles(e.igv_por_pagar)}</div>
                    )}
                    {e.declarado && e.igv_declarado !== null && (
                      <div className="text-xs text-slate-500">declarado {textoSoles(e.igv_declarado)}</div>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                    {!e.hay_datos || e.renta_por_pagar === null ? (
                      <span className="text-slate-400">—</span>
                    ) : (
                      <div className="font-semibold text-ink">{textoSoles(e.renta_por_pagar)}</div>
                    )}
                    {e.declarado && e.renta_declarada !== null && (
                      <div className="text-xs text-slate-500">declarado {textoSoles(e.renta_declarada)}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {e.declarado ? (
                      <span className="flex items-center gap-1 font-semibold text-emerald-700">
                        <CheckCircle2 size={13} /> Declarado
                      </span>
                    ) : !e.hay_datos ? (
                      <span className="font-semibold text-amber-700">Falta leer los datos de SUNAT</span>
                    ) : (
                      <span className="text-slate-600">Estimado</span>
                    )}
                    {e.hay_datos && e.avisos > 0 && (
                      <span className="mt-0.5 flex items-center gap-1 text-amber-700">
                        <AlertTriangle size={12} /> {e.avisos} aviso{e.avisos === 1 ? "" : "s"}
                      </span>
                    )}
                    {e.datos_al && (
                      <div className="mt-0.5 text-slate-400">
                        datos al {fechaHoraPeru(e.datos_al, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
                      </div>
                    )}
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
