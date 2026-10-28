"use client";
import { useEffect, useState } from "react";
import { AlertCircle, DatabaseZap, Loader2 } from "lucide-react";
import { api } from "../../../lib/api";
import { fechaHoraPeru, hoyPeru } from "../../../lib/fechas";
import { ESTADOS_LECTURA, ETAPAS_LECTURA, FUENTES_LECTURA, textoPeriodo } from "../../../lib/liquidacion";

// Bloque 1 de la Liquidacion en vivo: leer de SUNAT los datos de un periodo
// (0621, retenciones, percepciones, cuenta de control, Aduanas y SIRE) y ver
// el avance de cada fuente y lo que quedo guardado. Solo lectura en SUNAT.
const soles = new Intl.NumberFormat("es-PE", { style: "currency", currency: "PEN", maximumFractionDigits: 0 });
const SEGUNDOS_REFRESCO = 6;

function periodosElegibles() {
  const { anio, mes, dia } = hoyPeru();
  const lista = [0, 1, 2].map((atras) => {
    const total = anio * 12 + mes - 1 - atras;
    return `${Math.floor(total / 12)}-${String((total % 12) + 1).padStart(2, "0")}`;
  });
  // Hasta el dia 20 lo que se esta por declarar es el mes pasado.
  return { lista, porDefecto: dia <= 20 ? lista[1] : lista[0] };
}

function textoResumen(fuente, r) {
  if (!r) return "";
  switch (fuente) {
    case "declaraciones":
      return r.declaraciones.cantidad
        ? `${r.declaraciones.cantidad} periodos declarados · último: ${textoPeriodo(r.declaraciones.ultimo_periodo)}`
        : "Sin declaraciones guardadas";
    case "retenciones":
    case "percepciones":
      return `${r[fuente].cantidad} comprobante(s) del mes · ${soles.format(r[fuente].monto)}`;
    case "aduanas":
      return `${r.aduanas.cantidad} liquidación(es) del mes · ${soles.format(r.aduanas.monto)}`;
    case "cuenta_control":
      return r.cuenta_control.periodos
        ? `${r.cuenta_control.periodos} periodos · hasta ${textoPeriodo(r.cuenta_control.ultimo_periodo)}`
        : "Sin periodos guardados";
    case "sire":
      return `Ventas: ${r.ventas.cantidad} · IGV ${soles.format(r.ventas.igv)} — Compras: ${r.compras.cantidad} · IGV ${soles.format(r.compras.igv)}`;
    default:
      return "";
  }
}

export default function DatosSunatLiquidacion({ empresaId }) {
  const [{ lista, porDefecto }] = useState(periodosElegibles);
  const [periodo, setPeriodo] = useState(porDefecto);
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [pidiendo, setPidiendo] = useState(false);

  async function cargar() {
    try {
      setDatos(await api.verLecturasLiquidacion(empresaId, periodo));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    setDatos(null);
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empresaId, periodo]);

  useEffect(() => {
    if (!datos?.en_curso) return undefined;
    const reloj = setInterval(cargar, SEGUNDOS_REFRESCO * 1000);
    return () => clearInterval(reloj);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datos?.en_curso, empresaId, periodo]);

  async function leer() {
    setPidiendo(true);
    setError("");
    try {
      setDatos(await api.pedirLecturasLiquidacion(empresaId, periodo));
    } catch (err) {
      setError(err.message);
    } finally {
      setPidiendo(false);
    }
  }

  const porFuente = Object.fromEntries((datos?.lecturas || []).map((l) => [l.fuente, l]));

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-base font-bold text-ink">
          <DatabaseZap size={17} strokeWidth={1.75} className="text-accent" />
          Datos de SUNAT
        </h3>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={periodo}
            onChange={(e) => setPeriodo(e.target.value)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm capitalize focus:border-accent focus:outline-none"
          >
            {lista.map((p) => (
              <option key={p} value={p}>{textoPeriodo(p)}</option>
            ))}
          </select>
          {datos?.puede_leer && (
            <button
              onClick={leer}
              disabled={pidiendo || datos.en_curso}
              className="flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-sm font-bold text-white transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {(pidiendo || datos.en_curso) && <Loader2 size={14} className="animate-spin" />}
              {datos.en_curso ? "Leyendo..." : "Leer datos de SUNAT"}
            </button>
          )}
        </div>
      </div>
      <p className="mt-2 text-sm text-slate-600">
        Lee de SUNAT, solo consultando, todo lo que necesita el cálculo de {textoPeriodo(periodo)}. Toma unos 10 minutos;
        puedes salir de esta página mientras tanto.
      </p>

      {error && <div className="mt-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>}

      {!datos ? (
        !error && <p className="mt-4 text-sm text-slate-500">Cargando...</p>
      ) : (
        <ul className="mt-4 divide-y divide-slate-100">
          {FUENTES_LECTURA.map((f) => {
            const lectura = porFuente[f.id];
            const estado = lectura ? ESTADOS_LECTURA[lectura.estado] || ESTADOS_LECTURA.pendiente : null;
            return (
              <li key={f.id} className="py-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-ink">{f.texto}</div>
                    <div className="text-xs text-slate-500">{f.detalle}</div>
                  </div>
                  <div className="text-right">
                    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${estado ? estado.chip : "bg-slate-50 text-slate-400"}`}>
                      {lectura?.estado === "en_progreso" && lectura.etapa
                        ? ETAPAS_LECTURA[lectura.etapa] || estado.texto
                        : estado?.texto || "Sin leer"}
                    </span>
                    {lectura?.finalizado_en && (
                      <div className="mt-0.5 text-xs text-slate-400">{fechaHoraPeru(lectura.finalizado_en)}</div>
                    )}
                  </div>
                </div>
                <div className="mt-1 text-sm text-slate-700">{textoResumen(f.id, datos.resumen)}</div>
                {lectura?.estado === "error" && lectura.error && (
                  <div className="mt-1 flex items-start gap-1.5 text-xs text-red-600">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {lectura.error}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
