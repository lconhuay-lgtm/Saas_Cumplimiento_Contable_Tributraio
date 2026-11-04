"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Loader2, RefreshCw, Search } from "lucide-react";
import { api } from "../../lib/api";
import { fechaHoraPeru, fechaPeru, hoyPeruIso } from "../../lib/fechas";
import { ESTADOS_LIQUIDACION, ESTADOS_MES, periodosElegibles, textoPeriodo, textoRegimen, textoSoles } from "../../lib/liquidacion";
import ConfirmDialog from "../../components/ConfirmDialog";
import FiltroDigitoRuc, { coincideDigitoRuc } from "./FiltroDigitoRuc";

// Liquidacion en vivo en Cumplimiento, con el diseno del panel del boceto
// (Liquidación en vivo.html): totales, filtros y una fila por empresa activada
// ordenada por vencimiento, con las columnas del parametro 4.7, el estado del
// mes (4.8), "Requiere atencion" (4.6) y la marca "Revisado" (4.9). Clic en
// una empresa abre su tablero (cumplimiento/liquidacion/[id]).
const ALZA_DE_ATENCION = 0.15;
const DIAS_VENCE_PRONTO = 7;
const MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"];
const BOTON = "flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed";

function diasHasta(fecha) {
  return Math.round((Date.parse(fecha) - Date.parse(hoyPeruIso())) / 86400000);
}

function periodoCorto(periodo) {
  const [anio, mes] = periodo.split("-").map(Number);
  return `${MESES_CORTOS[mes - 1]} ${anio}`;
}

function anioAnterior(periodo) {
  return `${Number(periodo.slice(0, 4)) - 1}${periodo.slice(4)}`;
}

// Proyeccion al cierre (Fase 6): solo el mes en curso sin 0621 y con historial o datos del mes.
function proyeccionDe(e) {
  return e.proyeccion && !e.proyeccion.sin_base ? e.proyeccion : null;
}

// Frente al mismo mes del ano anterior; en el mes en curso, con lo proyectado al cierre (4.6).
function variacion(e) {
  const p = proyeccionDe(e);
  if ((!e.hay_datos && !p) || !e.igv_anio_anterior) return null;
  return ((p ? p.por_pagar : e.igv_681) - e.igv_anio_anterior) / e.igv_anio_anterior;
}

function textoVariacion(v) {
  return `${v >= 0 ? "+" : "−"}${Math.abs(Math.round(v * 100))} %`;
}

function listaDigitos(digitos) {
  return digitos.length > 1 ? `${digitos.slice(0, -1).join(", ")} y ${digitos.at(-1)}` : digitos[0];
}

function Tarjeta({ titulo, valor, nota, alerta }) {
  return (
    <div className={`rounded-xl border bg-white p-5 ${alerta ? "border-red-200" : "border-slate-200"}`}>
      <div className="text-sm text-slate-600">{titulo}</div>
      <div className={`mt-1 font-heading text-3xl font-bold tabular-nums ${alerta ? "text-red-700" : "text-ink"}`}>{valor}</div>
      <div className="mt-1 text-xs text-slate-600">{nota}</div>
    </div>
  );
}

export default function LiquidacionDelMes({ esAdmin, activas, incluidas }) {
  const [{ lista, porDefecto }] = useState(periodosElegibles);
  const [periodo, setPeriodo] = useState(porDefecto);
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [digitos, setDigitos] = useState([]);
  const [confirmar, setConfirmar] = useState(false);
  const [actualizando, setActualizando] = useState(false);

  useEffect(() => {
    let vigente = true;
    setDatos(null);
    setAviso("");
    api.verPanelLiquidacion(periodo)
      .then((data) => vigente && (setDatos(data), setError("")))
      .catch((err) => vigente && setError(err.message));
    return () => {
      vigente = false;
    };
  }, [periodo]);

  async function actualizarTodas() {
    setConfirmar(false);
    setActualizando(true);
    try {
      const r = await api.actualizarPanelLiquidacion(periodo);
      setAviso(
        `Se leen ${r.encoladas} empresa(s), una cada 2 minutos: terminan en unos ${r.minutos} minutos.` +
          (r.saltadas ? ` ${r.saltadas} ya tenían una lectura en curso o no tienen clave SOL.` : ""),
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setActualizando(false);
    }
  }

  const enCurso = periodo === hoyPeruIso().slice(0, 7);
  const mes = textoPeriodo(periodo).split(" ")[0];
  const corto = periodoCorto(anioAnterior(periodo));

  const visibles = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    return (datos?.empresas || []).filter(
      (e) => coincideDigitoRuc(e.ruc, digitos) && (!q || e.razon_social.toLowerCase().includes(q) || e.ruc.includes(q)),
    );
  }, [datos, busqueda, digitos]);

  const totales = useMemo(() => {
    const t = { igv: 0, sinDeclarar: 0, actual: 0, anterior: 0, proyectado: 0, conProyeccion: 0, vencen: [], alertas: 0, conAlertas: 0 };
    visibles.forEach((e) => {
      const p = proyeccionDe(e);
      if (e.hay_datos && !e.declarado) {
        t.igv += e.igv_por_pagar;
        t.sinDeclarar += 1;
      }
      if (p) {
        t.proyectado += p.igv;
        t.conProyeccion += 1;
      }
      // Comparacion con el ano anterior: lo proyectado en el mes en curso; lo estimado en un mes cerrado.
      if (!e.declarado && e.igv_anio_anterior !== null && (p || e.hay_datos)) {
        t.actual += p ? p.por_pagar : e.igv_681;
        t.anterior += e.igv_anio_anterior;
      }
      if (!e.declarado && e.vence && diasHasta(e.vence) >= 0 && diasHasta(e.vence) <= DIAS_VENCE_PRONTO) t.vencen.push(e.ruc.slice(-1));
      t.alertas += e.atencion.length;
      if (e.atencion.length) t.conAlertas += 1;
    });
    t.vencenDigitos = [...new Set(t.vencen)].sort();
    return t;
  }, [visibles]);

  const variacionTotal = totales.anterior ? (totales.actual - totales.anterior) / totales.anterior : null;

  return (
    <>
      <div className="mt-5 flex flex-wrap items-end justify-between gap-3">
        <label className="text-xs font-semibold text-slate-500">
          Periodo
          <select
            value={periodo}
            onChange={(e) => setPeriodo(e.target.value)}
            className="mt-1 block rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-normal capitalize text-ink focus:border-accent focus:outline-none"
          >
            {lista.map((p) => (
              <option key={p} value={p}>{textoPeriodo(p)}{p === hoyPeruIso().slice(0, 7) ? " (en curso)" : ""}</option>
            ))}
          </select>
        </label>
        <div className="flex flex-wrap gap-2">
          <button disabled title="Llega en la Fase 7" className={`${BOTON} border border-slate-200 bg-white text-slate-400`}>Excel</button>
          {esAdmin && (
            <button onClick={() => setConfirmar(true)} disabled={actualizando || !datos}
              className={`${BOTON} bg-accent font-bold text-white hover:opacity-90 disabled:opacity-60`}>
              {actualizando ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
              Actualizar todas
            </button>
          )}
        </div>
      </div>

      {error && <div className="mt-4 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>}
      {aviso && <div className="mt-4 rounded-lg border border-accent/20 bg-accent-light px-3 py-2.5 text-sm text-accent">{aviso}</div>}

      {datos && (
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tarjeta
            titulo={enCurso ? `IGV a pagar si ${mes} cerrara hoy` : `IGV a pagar de ${mes}`}
            valor={textoSoles(totales.igv)}
            nota={`suma de ${totales.sinDeclarar} empresa(s) sin declarar`}
          />
          <Tarjeta
            titulo="Proyección al cierre del mes"
            valor={!enCurso ? textoSoles(totales.igv) : totales.conProyeccion ? textoSoles(totales.proyectado) : "—"}
            nota={
              <>
                {enCurso
                  ? `orientativa · suma de ${totales.conProyeccion} empresa(s) con historial o datos`
                  : "El mes ya cerró: es el monto final"}
                {variacionTotal !== null && (
                  <span className={`block font-semibold ${variacionTotal >= ALZA_DE_ATENCION ? "text-red-700" : ""}`}>
                    {textoVariacion(variacionTotal)} frente a {textoPeriodo(anioAnterior(periodo))}
                  </span>
                )}
              </>
            }
          />
          <Tarjeta
            titulo={`Vencen en los próximos ${DIAS_VENCE_PRONTO} días`}
            valor={`${totales.vencen.length} empresa${totales.vencen.length === 1 ? "" : "s"}`}
            nota={totales.vencenDigitos.length ? `dígitos RUC ${listaDigitos(totales.vencenDigitos)}` : "ninguna sin declarar esta semana"}
          />
          <Tarjeta
            titulo="Alertas activas"
            valor={totales.alertas}
            nota={`en ${totales.conAlertas} empresa${totales.conAlertas === 1 ? "" : "s"}`}
            alerta={totales.alertas > 0}
          />
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
        <FiltroDigitoRuc digitos={digitos} onCambio={setDigitos} />
        <div className="relative">
          <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Empresa o RUC"
            className="w-64 rounded-lg border border-slate-200 bg-white py-1.5 pl-8 pr-3 text-sm focus:border-accent focus:outline-none"
          />
        </div>
      </div>

      <div className="mt-3 overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Empresa / RUC</th>
              <th className="px-4 py-3">Vence</th>
              <th className="px-4 py-3">Fuente</th>
              <th className="px-4 py-3 text-right">IGV hoy</th>
              <th className="px-4 py-3 text-right">Proyección cierre</th>
              <th className="px-4 py-3 text-right">vs. {corto}</th>
              <th className="px-4 py-3 text-right">Renta</th>
              <th className="px-4 py-3">Situación</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {!datos && !error && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-slate-500">Calculando...</td>
              </tr>
            )}
            {datos && visibles.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-slate-500">
                  Ninguna empresa activada con estos filtros. Actívalas en la vista «Configuración».
                </td>
              </tr>
            )}
            {visibles.map((e) => {
              const dias = e.vence ? diasHasta(e.vence) : null;
              const v = variacion(e);
              const p = proyeccionDe(e);
              const config = e.estado_config !== "lista" ? ESTADOS_LIQUIDACION[e.estado_config] : null;
              const estado = ESTADOS_MES[e.estado_mes] || ESTADOS_MES.en_curso;
              const montoIgv = e.saldo_a_favor ? textoSoles(e.saldo_a_favor) : textoSoles(e.igv_por_pagar);
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
                    {e.vence ? (
                      <>
                        <div className="text-ink">{fechaPeru(e.vence, { timeZone: "UTC" })}</div>
                        <div className={`text-xs ${!e.declarado && dias <= 3 ? "font-semibold text-red-600" : "text-slate-500"}`}>
                          {dias < 0 ? "vencido" : dias === 0 ? "hoy" : `en ${dias} día${dias === 1 ? "" : "s"}`}
                        </div>
                      </>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600">
                    {e.declarado
                      ? "Declaración 0621 presentada"
                      : e.lectura_sire
                        ? <>SIRE · propuesta<div className="text-slate-400">al {fechaPeru(e.lectura_sire, { day: "2-digit", month: "2-digit" })}</div></>
                        : "—"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                    {!e.hay_datos ? (
                      <span className="text-slate-400">—</span>
                    ) : (
                      <>
                        <div className={`font-bold ${e.saldo_a_favor ? "text-emerald-700" : "text-ink"}`}>{montoIgv}</div>
                        {e.saldo_a_favor > 0 && <div className="text-xs text-slate-500">saldo a favor</div>}
                        {e.declarado && e.igv_declarado !== null && (
                          <div className="text-xs text-slate-500">declarado {textoSoles(e.igv_declarado)}</div>
                        )}
                      </>
                    )}
                  </td>
                  {enCurso ? (
                    <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                      {!p ? (
                        <span className="text-slate-400">—</span>
                      ) : (
                        <>
                          <div className={p.saldo_a_favor ? "text-emerald-700" : "text-ink"}>{textoSoles(p.saldo_a_favor || p.igv)}</div>
                          <div className="text-xs text-slate-400">
                            {p.saldo_a_favor ? "saldo a favor" : p.maximo > p.minimo ? `${textoSoles(p.minimo)} a ${textoSoles(p.maximo)}` : ""}
                          </div>
                        </>
                      )}
                    </td>
                  ) : (
                    <td className={`whitespace-nowrap px-4 py-3 text-right tabular-nums ${e.saldo_a_favor ? "text-emerald-700" : "text-slate-600"}`}>
                      {!e.hay_datos ? <span className="text-slate-400">—</span> : montoIgv}
                    </td>
                  )}
                  <td className={`whitespace-nowrap px-4 py-3 text-right tabular-nums ${v !== null && v >= ALZA_DE_ATENCION ? "font-bold text-red-700" : "text-slate-600"}`}>
                    {v === null ? <span className="font-normal text-slate-400">—</span> : textoVariacion(v)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-slate-600">
                    {!e.hay_datos || e.renta_por_pagar === null ? <span className="text-slate-400">—</span> : textoSoles(e.renta_por_pagar)}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {config ? (
                      <>
                        <span className={`rounded-full px-2.5 py-1 font-semibold ${config.chip}`}>{config.texto}</span>
                        <div className="mt-1.5">
                          <Link href={`/empresas/${e.empresa_id}?tab=liquidacion`} className="text-accent underline">Configurar</Link>
                          {" · "}
                          <Link href="/liquidacion/guia" target="_blank" className="text-accent underline">Guía</Link>
                        </div>
                      </>
                    ) : (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className={`rounded-full px-2.5 py-1 font-semibold ${estado.chip}`}>{estado.texto}</span>
                        <span
                          title={e.atencion.join("\n")}
                          className={`rounded-full px-2.5 py-1 font-semibold ${e.atencion.length ? "bg-red-50 text-red-700" : "bg-emerald-50 text-emerald-700"}`}
                        >
                          {e.atencion.length ? `${e.atencion.length} alerta${e.atencion.length === 1 ? "" : "s"}` : "Sin alertas"}
                        </span>
                      </div>
                    )}
                    {e.revisado && (
                      <div className="mt-1.5 flex items-center gap-1 text-slate-500">
                        <CheckCircle2 size={12} className="text-emerald-600" />
                        Revisado{e.revisado.usuario_nombre ? ` por ${e.revisado.usuario_nombre}` : ""} ·{" "}
                        {fechaHoraPeru(e.revisado.fecha, { day: "2-digit", month: "2-digit" })}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Ordenado por fecha de vencimiento. Clic en una empresa para abrir su tablero.
        {activas !== undefined && incluidas ? ` Activas: ${activas} de ${incluidas} incluidas en tu plan.` : ""}
      </p>

      {confirmar && (
        <ConfirmDialog
          titulo={`¿Leer ahora el SIRE y Aduanas de ${textoPeriodo(periodo)}?`}
          mensaje={`Se leen las ${datos?.empresas.length || 0} empresas activadas, una cada 2 minutos (unos ${Math.ceil((datos?.empresas.length || 0) * 2)} minutos en total). Las retenciones, percepciones y el 0621 siguen con su lectura de madrugada.`}
          textoConfirmar="Sí, actualizar"
          onConfirmar={actualizarTodas}
          onCancelar={() => setConfirmar(false)}
        />
      )}
    </>
  );
}
