"use client";
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, ChevronRight, Loader2, X } from "lucide-react";
import Sidebar from "../../../../../components/Sidebar";
import { api, getToken } from "../../../../../lib/api";
import { hoyPeruIso } from "../../../../../lib/fechas";
import { periodosElegibles, textoPeriodo, textoSoles } from "../../../../../lib/liquidacion";

// Revision de compras y credito fiscal (Fase 5), como la pantalla 3 del boceto
// (Liquidación en vivo.html): cada compra del registro del SIRE cruzada con los
// depositos de detraccion, cuanto credito cuenta en el mes y la decision del
// responsable (incluir o excluir con motivo, reglas por proveedor). Lo que se
// decide aqui solo cambia el calculo de la liquidacion, no el registro en SUNAT.
const PANEL = "/cumplimiento?tab=liquidacion";
const BOTON =
  "inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-semibold text-slate-600 shadow-sm transition-colors hover:border-accent hover:text-accent";

const TIPOS = { "01": "Factura", "02": "Recibo por honorarios", "03": "Boleta", "07": "Nota de crédito", "08": "Nota de débito",
  "12": "Ticket", "14": "Recibo de servicios públicos", "50": "DAM" };

const TONO_DETRACCION = {
  pagada: "bg-emerald-50 text-emerald-700",
  por_depositar: "bg-amber-50 text-amber-800",
  vencida: "bg-red-50 text-red-700",
  verificar: "bg-violet-50 text-violet-700",
  no_sujeta: "bg-slate-100 text-slate-600",
};
const TONO_CREDITO = {
  cuenta: "text-emerald-700",
  pasa: "text-accent",
  por_confirmar: "text-amber-700",
  en_riesgo: "text-amber-700",
  suspendido: "text-red-700",
  excluido: "text-red-700",
};
const OTRO = "Otro";
const CONSTANCIA = "Detracción depositada (constancia en mano)";

function mesDe(periodo) {
  return textoPeriodo(periodo).split(" ")[0];
}

/** "2026-10-15" -> "15/10/2026" (fechas sin hora: no se pasan por la zona horaria). */
function dia(iso, conAnio = true) {
  if (!iso) return "";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return conAnio ? `${d}/${m}/${a}` : `${d}/${m}`;
}

function comprobante(f) {
  return `${TIPOS[f.tipo_comprobante] || `Tipo ${f.tipo_comprobante}`} ${f.serie}-${f.numero}`;
}

export default function ComprasPage() {
  // useSearchParams() exige un limite de Suspense en el build (como cumplimiento/page.js).
  return (
    <Suspense fallback={null}>
      <Compras />
    </Suspense>
  );
}

function Compras() {
  const { id } = useParams();
  const router = useRouter();
  const buscados = useSearchParams();
  const [{ lista: periodos, porDefecto }] = useState(periodosElegibles);
  const [periodo, setPeriodo] = useState(buscados.get("periodo") || porDefecto);
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [filtro, setFiltro] = useState("todos");
  const [abierta, setAbierta] = useState(null);
  const [aviso, setAviso] = useState("");

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setDatos(null);
    setError("");
    api.verComprasLiquidacion(id, periodo).then(setDatos).catch((err) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, periodo]);

  async function quitarRegla(regla) {
    try {
      setDatos(await api.quitarReglaProveedor(id, regla.id, periodo));
    } catch (err) {
      setError(err.message);
    }
  }

  async function leerHistorial() {
    setAviso("");
    try {
      const r = await api.leerHistorialCompras(id);
      setAviso(`Se están leyendo las compras de ${textoPeriodo(r.desde)} a ${textoPeriodo(r.hasta)} (unos 25 minutos). Vuelve a abrir esta página después.`);
    } catch (err) {
      setAviso(err.message);
    }
  }

  const lista = [...new Set([periodo, ...periodos])].sort().reverse();
  const visibles = datos ? datos.filas.filter((f) => filtro === "todos" || f.grupo === filtro) : [];
  const mes = mesDe(periodo);

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 pb-8 pt-24 xl:px-12">
        <nav className="flex flex-wrap items-center gap-1 text-sm text-slate-500">
          <Link href={PANEL} className="hover:text-accent">Liquidación en vivo</Link>
          <ChevronRight size={14} />
          <Link href={`/cumplimiento/liquidacion/${id}`} className="hover:text-accent">{datos?.razon_social || "..."}</Link>
          <ChevronRight size={14} />
          <span className="font-semibold text-ink">Compras y crédito fiscal · {textoPeriodo(periodo)}</span>
        </nav>

        <div className="mt-4 flex flex-wrap items-start justify-between gap-3">
          <div className="max-w-3xl">
            <h1 className="font-heading text-3xl font-bold tracking-tight text-ink">Revisión de compras y crédito fiscal</h1>
            <p className="mt-1 text-sm text-slate-600">
              Cada compra del registro (propuesta del SIRE) cruzada con los depósitos de detracción. Lo que incluyas o excluyas
              aquí cambia solo el cálculo de la liquidación: el registro en SUNAT no se modifica.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-sm font-semibold text-slate-600">
              Periodo
              <select
                value={periodo}
                onChange={(e) => setPeriodo(e.target.value)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-ink"
              >
                {lista.map((p) => (
                  <option key={p} value={p}>
                    {textoPeriodo(p)}{p === hoyPeruIso().slice(0, 7) ? " (en curso)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <Link href={`/cumplimiento/liquidacion/${id}`} className={BOTON}>
              <ArrowLeft size={15} strokeWidth={1.5} />
              Volver al tablero
            </Link>
          </div>
        </div>

        {error && <div className="mt-6 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>}
        {!datos && !error && <p className="mt-8 text-sm text-slate-500">Cargando...</p>}

        {datos && (
          <>
            <Tarjetas resumen={datos.resumen} periodo={periodo} />

            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
              <span>
                {datos.resumen.detracciones_al
                  ? `Depósitos de detracción leídos hasta el ${dia(datos.resumen.detracciones_al)}.`
                  : "Aún no se leen los depósitos de detracción de esta empresa."}
              </span>
              <span>IGV de compras del registro: {textoSoles(datos.resumen.registro)}.</span>
              {datos.puede_decidir && (
                <button onClick={leerHistorial} className="font-semibold text-accent hover:underline">
                  Leer los 12 meses anteriores de compras
                </button>
              )}
            </div>
            {aviso && <div className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-700">{aviso}</div>}
            {!datos.hay_compras && (
              <div className="mt-4 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2.5 text-sm text-amber-800">
                Todavía no se leen las compras del SIRE de {textoPeriodo(periodo)}. Usa «Leer datos de SUNAT» en el tablero.
              </div>
            )}

            <div className="mt-5 flex flex-wrap gap-2">
              <Filtro activo={filtro === "todos"} onClick={() => setFiltro("todos")}>Todos · {datos.filas.length}</Filtro>
              {datos.grupos.map((g) => (
                <Filtro key={g.clave} activo={filtro === g.clave} onClick={() => setFiltro(g.clave)}>
                  {g.nombre} · {g.cantidad}
                </Filtro>
              ))}
            </div>

            <div className="mt-3 overflow-x-auto rounded-xl border border-slate-200 bg-white">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="px-4 py-3">Comprobante</th>
                    <th className="px-4 py-3 text-right">IGV</th>
                    <th className="px-4 py-3">Detracción</th>
                    <th className="px-4 py-3">Crédito en {mes}</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {visibles.map((f) => (
                    <tr key={f.car} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                      <td className="px-4 py-3">
                        <div className="font-semibold text-ink">{f.proveedor || "Sin nombre"}</div>
                        <div className="text-xs text-slate-500">
                          {comprobante(f)} · {dia(f.fecha_emision)}
                          {f.periodo !== periodo && ` · registro de ${mesDe(f.periodo)}`}
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right font-semibold tabular-nums text-ink">{textoSoles(f.igv)}</td>
                      <td className="px-4 py-3">
                        <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${TONO_DETRACCION[f.estado]}`}>{f.detraccion_texto}</span>
                        <div className="mt-1 text-xs text-slate-500">{f.detraccion_nota}</div>
                      </td>
                      <td className="px-4 py-3">
                        <div className={`font-semibold ${TONO_CREDITO[f.credito]}`}>{f.credito_texto}</div>
                        {f.credito_nota && <div className="text-xs text-slate-500">{f.credito_nota}</div>}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button onClick={() => setAbierta(f)} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-accent hover:border-accent">
                          Revisar
                        </button>
                      </td>
                    </tr>
                  ))}
                  {!visibles.length && (
                    <tr>
                      <td colSpan={5} className="px-4 py-6 text-center text-sm text-slate-500">No hay compras en este grupo.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <Reglas reglas={datos.reglas} puedeDecidir={datos.puede_decidir} onQuitar={quitarRegla} />
          </>
        )}

        {abierta && datos && (
          <Revisar
            fila={abierta}
            periodo={periodo}
            motivos={datos.motivos}
            puedeDecidir={datos.puede_decidir}
            onCerrar={() => setAbierta(null)}
            onGuardar={async (decision) => {
              const nuevos = await api.decidirCompraLiquidacion(id, abierta.car, { periodo, ...decision });
              setDatos(nuevos);
              setAbierta(null);
            }}
          />
        )}
      </main>
    </div>
  );
}

function Filtro({ activo, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-3.5 py-1.5 text-xs font-semibold transition-colors ${
        activo ? "bg-accent text-white" : "border border-slate-200 bg-white text-slate-600 hover:border-accent hover:text-accent"
      }`}
    >
      {children}
    </button>
  );
}

function Tarjeta({ titulo, valor, tono, children }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="text-sm text-slate-600">{titulo}</div>
      <div className={`mt-1 font-heading text-3xl font-bold tabular-nums ${tono}`}>{valor}</div>
      <div className="mt-1.5 text-xs text-slate-500">{children}</div>
    </div>
  );
}

function Tarjetas({ resumen, periodo }) {
  const mes = mesDe(periodo);
  return (
    <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Tarjeta titulo="Crédito fiscal que cuenta este mes" valor={textoSoles(resumen.credito_cuenta)} tono="text-ink">
        {resumen.credito_viene
          ? `Incluye ${textoSoles(resumen.credito_viene)} de meses anteriores (detracción pagada en ${mes})`
          : "Sin contar lo que todavía depende de depositar la detracción"}
      </Tarjeta>
      <Tarjeta titulo="En riesgo: falta depositar la detracción" valor={textoSoles(resumen.en_riesgo)} tono="text-amber-700">
        {resumen.en_riesgo_cantidad
          ? `${resumen.en_riesgo_cantidad} factura(s) · deposita hasta el ${dia(resumen.en_riesgo_plazo, false)} para usarlo en ${mes}`
          : "Nada pendiente de depositar"}
      </Tarjeta>
      <Tarjeta titulo="Suspendido: detracción no depositada" valor={textoSoles(resumen.suspendido)} tono="text-red-700">
        {resumen.suspendido_cantidad
          ? `${resumen.suspendido_cantidad} factura(s) · cuenta en el mes en que se deposite`
          : "Ninguna detracción vencida sin depositar"}
      </Tarjeta>
      <Tarjeta
        titulo="Por verificar si lleva detracción"
        valor={`${resumen.por_verificar} factura${resumen.por_verificar === 1 ? "" : "s"}`}
        tono="text-violet-700"
      >
        S/ 700 o más de un proveedor con detracciones anteriores, o depósito que no cuadra
      </Tarjeta>
    </div>
  );
}

function Reglas({ reglas, puedeDecidir, onQuitar }) {
  if (!reglas.length) return null;
  return (
    <div className="mt-6 rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="font-heading text-lg font-bold text-ink">Reglas por proveedor</h2>
      <p className="mt-0.5 text-xs text-slate-500">Rigen desde el mes indicado en adelante. Al quitarlas, sus compras vuelven a lo automático.</p>
      <ul className="mt-3 divide-y divide-slate-100">
        {reglas.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
            <div>
              <span className="font-semibold text-ink">{r.nombre_proveedor || r.ruc_proveedor}</span>
              <span className="text-slate-500"> · RUC {r.ruc_proveedor}</span>
              <div className="text-xs text-slate-500">
                {r.regla === "excluir" ? "Excluido siempre del crédito" : "Siempre factura con detracción"} desde {textoPeriodo(r.desde_periodo)}
                {r.motivo && ` · ${r.motivo}`} · {r.usuario_nombre}
              </div>
            </div>
            {puedeDecidir && (
              <button onClick={() => onQuitar(r)} className="text-xs font-semibold text-red-600 hover:underline">Quitar regla</button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Opcion({ name, value, actual, onChange, disabled, children }) {
  return (
    <label className={`flex items-start gap-2.5 py-1.5 text-sm ${disabled ? "text-slate-400" : "text-ink"}`}>
      <input type="radio" name={name} value={value} checked={actual === value} onChange={() => onChange(value)} disabled={disabled} className="mt-0.5" />
      <span>{children}</span>
    </label>
  );
}

function explicacion(f) {
  if (f.lleva === "no") return `No lleva detracción: ${f.detraccion_nota.toLowerCase()}.`;
  const partes = [];
  if (f.descripcion_codigo) partes.push(`${f.descripcion_codigo} (código ${f.codigo}${f.tasa ? `, ${+(f.tasa * 100).toFixed(2)} %` : ""})`);
  if (f.esperado) partes.push(`detracción esperada ${textoSoles(f.esperado)}`);
  if (f.depositos.length) {
    partes.push(`depósitos: ${f.depositos.map((d) => `constancia ${d.constancia} del ${dia(d.fecha, false)} por ${textoSoles(d.monto)}`).join("; ")}`);
  } else {
    partes.push("no hay depósito todavía");
  }
  const texto = partes.join(" · ");
  return `${texto[0].toUpperCase()}${texto.slice(1)}. Si se deposita hasta el ${dia(f.plazo)} (quinto día hábil de ${mesDe(
    `${f.plazo.slice(0, 7)}`
  )}), el crédito cuenta en ${mesDe(f.periodo)}; si no, pasa al mes en que se deposite.`;
}

function Revisar({ fila: f, periodo, motivos, puedeDecidir, onCerrar, onGuardar }) {
  const previa = f.decision;
  const reglaLleva = f.regla?.regla === "lleva_detraccion";
  const [lleva, setLleva] = useState(previa?.lleva && previa.lleva !== "auto" ? previa.lleva : reglaLleva ? "siempre" : "auto");
  const [credito, setCredito] = useState(previa?.credito || "auto");
  const [motivo, setMotivo] = useState(previa?.motivo || "");
  const [comentario, setComentario] = useState(previa?.comentario || "");
  const [constancia, setConstancia] = useState(previa?.constancia || "");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const mes = mesDe(f.periodo);

  async function guardar() {
    setError("");
    if (credito !== "auto" && !motivo) return setError("Elige un motivo para incluir o excluir la compra.");
    if (motivo === OTRO && !comentario.trim()) return setError("Con el motivo «Otro» escribe un comentario.");
    setGuardando(true);
    try {
      await onGuardar({ lleva: lleva === "siempre" && reglaLleva ? "auto" : lleva, credito, motivo, comentario, constancia });
    } catch (err) {
      setError(err.message);
      setGuardando(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-6" onClick={onCerrar}>
      <div className="max-h-full w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Revisar comprobante</div>
            <h2 className="mt-1 font-heading text-xl font-bold text-ink">{f.proveedor || "Sin nombre"}</h2>
            <div className="text-xs text-slate-500">
              {comprobante(f)} · {dia(f.fecha_emision)} {f.ruc && `· RUC ${f.ruc}`}
              {f.periodo !== periodo && ` · registro de ${mes}`}
            </div>
          </div>
          <button onClick={onCerrar} className="rounded-lg border border-slate-200 p-1.5 text-slate-500 hover:text-ink" aria-label="Cerrar">
            <X size={16} />
          </button>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-slate-50 p-3 text-sm">
            <div className="text-xs text-slate-500">Total</div>
            <div className="font-semibold tabular-nums text-ink">{textoSoles(f.total)}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3 text-sm">
            <div className="text-xs text-slate-500">IGV (crédito)</div>
            <div className="font-semibold tabular-nums text-ink">{textoSoles(f.igv)}</div>
          </div>
        </div>

        <h3 className="mt-5 font-heading text-base font-bold text-ink">Detracción</h3>
        <p className="mt-1 text-sm text-slate-600">{explicacion(f)}</p>
        <div className="mt-3 text-sm font-semibold text-slate-700">¿Esta compra lleva detracción?</div>
        <Opcion name="lleva" value="auto" actual={lleva} onChange={setLleva} disabled={!puedeDecidir}>
          Lo que indica el sistema <span className="text-slate-500">({f.lleva === "si" ? "sí lleva" : f.lleva === "no" ? "no lleva" : "por verificar"})</span>
        </Opcion>
        <Opcion name="lleva" value="si" actual={lleva} onChange={setLleva} disabled={!puedeDecidir}>Sí, esta factura</Opcion>
        <Opcion name="lleva" value="siempre" actual={lleva} onChange={setLleva} disabled={!puedeDecidir || reglaLleva}>
          Sí, este proveedor siempre factura con detracción
        </Opcion>
        <Opcion name="lleva" value="no" actual={lleva} onChange={setLleva} disabled={!puedeDecidir}>No lleva detracción</Opcion>

        <h3 className="mt-5 border-t border-slate-100 pt-4 font-heading text-base font-bold text-ink">Crédito fiscal en {mes}</h3>
        <p className="mt-1 text-sm text-slate-600">
          Automático según la detracción: <span className="font-semibold text-ink">{f.credito_automatico.toLowerCase()}</span>
        </p>
        <div className="mt-2 text-sm font-semibold text-slate-700">Decisión del responsable</div>
        <Opcion name="credito" value="auto" actual={credito} onChange={setCredito} disabled={!puedeDecidir}>Usar el automático</Opcion>
        <Opcion name="credito" value="incluir" actual={credito} onChange={setCredito} disabled={!puedeDecidir}>Incluir en el crédito de este mes</Opcion>
        <Opcion name="credito" value="excluir" actual={credito} onChange={setCredito} disabled={!puedeDecidir}>Excluir del crédito</Opcion>
        <Opcion name="credito" value="excluir_siempre" actual={credito} onChange={setCredito} disabled={!puedeDecidir}>
          Excluir siempre a este proveedor
        </Opcion>

        <label className="mt-3 block text-sm font-semibold text-slate-700">
          Motivo <span className="font-normal text-slate-500">(obligatorio al incluir o excluir a mano)</span>
          <select
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
            disabled={!puedeDecidir}
            className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-normal text-ink"
          >
            <option value="">Elige un motivo</option>
            {motivos.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
        {motivo === CONSTANCIA && (
          <label className="mt-3 block text-sm font-semibold text-slate-700">
            Número de constancia
            <input
              value={constancia}
              onChange={(e) => setConstancia(e.target.value)}
              disabled={!puedeDecidir}
              maxLength={40}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-normal text-ink"
            />
          </label>
        )}
        <label className="mt-3 block text-sm font-semibold text-slate-700">
          Comentario
          <textarea
            value={comentario}
            onChange={(e) => setComentario(e.target.value)}
            disabled={!puedeDecidir}
            maxLength={500}
            rows={2}
            placeholder={motivo === OTRO ? "Obligatorio con «Otro»" : "Opcional"}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-normal text-ink"
          />
        </label>

        {error && <div className="mt-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-600">{error}</div>}

        <div className="mt-4 flex gap-2">
          {puedeDecidir && (
            <button
              onClick={guardar}
              disabled={guardando}
              className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-dark disabled:opacity-60"
            >
              {guardando && <Loader2 size={14} className="animate-spin" />}
              Guardar
            </button>
          )}
          <button onClick={onCerrar} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:text-ink">
            Cerrar
          </button>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          {previa
            ? `Última decisión: ${previa.usuario_nombre || "sin nombre"}, ${dia(previa.fecha)}. `
            : ""}
          Solo el responsable asignado (o un administrador) puede cambiarlo. Queda registrado quién, cuándo y el motivo. No
          modifica el registro en SUNAT.
        </p>
      </div>
    </div>
  );
}
