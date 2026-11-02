"use client";
import { useEffect, useState } from "react";
import { AlertTriangle, Calculator, CheckCircle2 } from "lucide-react";
import { api } from "../../../lib/api";
import { fechaHoraPeru, fechaPeru, hoyPeruIso } from "../../../lib/fechas";
import { textoPeriodo, textoSoles } from "../../../lib/liquidacion";

// Bloque 2 de la Liquidacion en vivo: el estimado del IGV y la Renta del
// periodo si el mes cerrara hoy (backend/app/calculo_liquidacion.py), con
// "como se llega al monto" casilla por casilla y, si ya se presento el 0621,
// lo declarado al lado. Una diferencia de mas de S/ 10 se marca (parametro 7.1).
const UMBRAL_DIFERENCIA = 10;

function diasHasta(fecha) {
  return Math.round((Date.parse(fecha) - Date.parse(hoyPeruIso())) / 86400000);
}

function textoVence(vence) {
  if (!vence) return "Sin fecha de vencimiento en el cronograma";
  const dias = diasHasta(vence);
  const fecha = fechaPeru(vence, { timeZone: "UTC" });
  if (dias < 0) return `Venció el ${fecha}`;
  if (dias === 0) return `Vence hoy, ${fecha}`;
  return `Vence el ${fecha} (en ${dias} día${dias === 1 ? "" : "s"})`;
}

function Monto({ linea }) {
  if (linea.monto === null || linea.monto === undefined) return <span className="text-slate-400">—</span>;
  return <>{linea.signo < 0 && linea.monto ? "− " : ""}{textoSoles(linea.monto)}</>;
}

function TablaLineas({ titulo, lineas, conDeclarado }) {
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
          <tr className="border-b border-slate-200">
            <th className="w-16 py-2 pr-2">Casilla</th>
            <th className="py-2 pr-2">{titulo}</th>
            <th className="py-2 pr-2 text-right">Estimado</th>
            {conDeclarado && <th className="py-2 pr-2 text-right">Declarado</th>}
            <th className="hidden py-2 pl-3 md:table-cell">De dónde sale</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {lineas.map((l, i) => {
            const fuerte = l.tipo === "subtotal" || l.tipo === "total";
            const diferencia = conDeclarado && l.declarado !== null && l.monto !== null && Math.abs(l.monto - l.declarado) > UMBRAL_DIFERENCIA;
            return (
              <tr key={`${l.casilla}-${i}`} className={l.tipo === "total" ? "bg-slate-50" : ""}>
                <td className="py-2 pr-2 font-mono text-xs text-slate-500">{l.casilla || ""}</td>
                <td className={`py-2 pr-2 ${fuerte ? "font-bold text-ink" : "text-slate-700"}`}>{l.concepto}</td>
                <td className={`whitespace-nowrap py-2 pr-2 text-right tabular-nums ${fuerte ? "font-bold text-ink" : "text-slate-700"}`}>
                  <Monto linea={l} />
                </td>
                {conDeclarado && (
                  <td className={`whitespace-nowrap py-2 pr-2 text-right tabular-nums ${diferencia ? "font-bold text-amber-700" : "text-slate-500"}`}>
                    {l.declarado === null ? "—" : textoSoles(l.declarado)}
                  </td>
                )}
                <td className="hidden py-2 pl-3 text-xs text-slate-500 md:table-cell">{l.fuente || ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function TableroLiquidacion({ empresaId, periodo, periodos, onPeriodo, version }) {
  const [calculo, setCalculo] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let vigente = true;
    setCalculo(null);
    api.verCalculoLiquidacion(empresaId, periodo)
      .then((data) => vigente && (setCalculo(data), setError("")))
      .catch((err) => vigente && setError(err.message));
    return () => {
      vigente = false;
    };
  }, [empresaId, periodo, version]);

  const conDeclarado = Boolean(calculo?.declarado);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-base font-bold text-ink">
            <Calculator size={17} strokeWidth={1.75} className="text-accent" />
            <span>Liquidación de <span className="capitalize">{textoPeriodo(periodo)}</span></span>
          </h3>
          <p className="mt-1 text-sm text-slate-600">
            Lo que se pagaría si el mes cerrara hoy, con los datos leídos de SUNAT
            {calculo?.datos_al ? ` (datos al ${fechaHoraPeru(calculo.datos_al, { dateStyle: "short", timeStyle: "short" })})` : ""}.
          </p>
        </div>
        <select
          value={periodo}
          onChange={(e) => onPeriodo(e.target.value)}
          className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm capitalize focus:border-accent focus:outline-none"
        >
          {periodos.map((p) => (
            <option key={p} value={p}>{textoPeriodo(p)}</option>
          ))}
        </select>
      </div>

      {error && <div className="mt-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>}
      {!calculo && !error && <p className="mt-4 text-sm text-slate-500">Calculando...</p>}

      {calculo && (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-slate-200 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {calculo.saldo_a_favor ? "IGV: saldo a favor" : "IGV por pagar"}
              </div>
              <div className={`mt-1 text-2xl font-extrabold ${calculo.saldo_a_favor ? "text-emerald-700" : "text-ink"}`}>
                {textoSoles(calculo.saldo_a_favor || calculo.igv_por_pagar)}
              </div>
              <div className="mt-0.5 text-xs text-slate-500">
                {calculo.saldo_a_favor ? "Pasa al mes siguiente" : "Casilla 681 menos pagos ya hechos"}
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Renta por pagar</div>
              <div className="mt-1 text-2xl font-extrabold text-ink">
                {calculo.renta_por_pagar === null ? "—" : textoSoles(calculo.renta_por_pagar)}
              </div>
              <div className="mt-0.5 text-xs text-slate-500">
                {calculo.renta_porcentaje === null ? "Falta el régimen" : `Pago a cuenta de ${(calculo.renta_porcentaje * 100).toFixed(2)} %`}
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Vencimiento</div>
              <div className="mt-1 text-sm font-bold text-ink">{textoVence(calculo.vence)}</div>
              <div className="mt-0.5 text-xs text-slate-500">Según el último dígito del RUC</div>
            </div>
          </div>

          {calculo.declarado && (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-800">
              <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
              <span>
                Ya se presentó el 0621 (orden {calculo.declarado.num_orden}
                {calculo.declarado.fecha_presentacion ? `, ${fechaPeru(calculo.declarado.fecha_presentacion, { timeZone: "UTC" })}` : ""}).
                La columna «Declarado» muestra lo presentado; en ámbar, las casillas que difieren en más de S/ {UMBRAL_DIFERENCIA}.
              </span>
            </div>
          )}

          {calculo.avisos.length > 0 && (
            <ul className="mt-4 space-y-1.5 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2.5 text-sm text-amber-800">
              {calculo.avisos.map((a) => (
                <li key={a} className="flex items-start gap-2">
                  <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                  {a}
                </li>
              ))}
            </ul>
          )}

          <h4 className="mt-5 text-sm font-bold text-ink">Cómo se llega al IGV</h4>
          <TablaLineas titulo="Concepto" lineas={calculo.lineas_igv} conDeclarado={conDeclarado} />
          <h4 className="mt-5 text-sm font-bold text-ink">Pasa al mes siguiente</h4>
          <TablaLineas titulo="Concepto" lineas={calculo.lineas_siguiente} conDeclarado={conDeclarado} />
          <h4 className="mt-5 text-sm font-bold text-ink">Cómo se llega a la Renta</h4>
          <TablaLineas titulo="Concepto" lineas={calculo.lineas_renta} conDeclarado={conDeclarado} />
          <p className="mt-4 text-xs text-slate-500">
            Estimado en soles enteros, como el 0621. Las ventas y compras salen de la propuesta del SIRE: si el registro
            final excluye o agrega comprobantes, el monto declarado puede cambiar.
          </p>
        </>
      )}
    </div>
  );
}
