"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Download,
  FileText,
  Loader2,
  RefreshCw,
  Search,
  X,
  XCircle,
} from "lucide-react";
import { api } from "../../lib/api";
import { descargarCsv, periodoPorDefecto } from "./utilidades";
import FiltroDigitoRuc, { coincideDigitoRuc } from "./FiltroDigitoRuc";
import { fechaPeru, hoyPeruIso } from "../../lib/fechas";

const MESES_CORTOS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Set", "Oct", "Nov", "Dic"];
const MESES_LARGOS = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Setiembre", "Octubre", "Noviembre", "Diciembre",
];

// Formularios que controla el cuadro (los mismos que backend/app/routers/declaraciones.py).
const FORMULARIOS = {
  "0621": "IGV-Renta (0621)",
  "0601": "PLAME (0601)",
};
const OPCIONES_FORMULARIO = [
  { id: "ambos", label: "IGV-Renta y PLAME" },
  { id: "0621", label: "IGV-Renta (0621)" },
  { id: "0601", label: "PLAME (0601)" },
];

const FILTROS_ESTADO = [
  { id: "todas", label: "Todas" },
  { id: "no_presentado", label: "No presentado" },
  { id: "pendiente", label: "Pendiente" },
  { id: "presentado", label: "Presentado" },
];

const ESTILO = {
  presentado: { texto: "Presentado", celda: "bg-emerald-50 text-emerald-600", chip: "bg-emerald-50 text-emerald-700", Icon: CheckCircle2 },
  pendiente: { texto: "Pendiente", celda: "bg-amber-50 text-amber-500", chip: "bg-amber-50 text-amber-700", Icon: Clock },
  no_presentado: { texto: "No presentado", celda: "bg-red-50 text-red-500", chip: "bg-red-50 text-red-700", Icon: XCircle },
  no_aplica: { texto: "No aplica", celda: "text-slate-300", chip: "bg-slate-100 text-slate-500", Icon: null },
  futuro: { texto: "Aun no corresponde", celda: "text-slate-200", chip: "bg-slate-50 text-slate-400", Icon: null },
  sin_leer: { texto: "Sin leer", celda: "text-slate-200", chip: "bg-slate-50 text-slate-400", Icon: null },
};
const PESO = { no_presentado: 3, pendiente: 2, presentado: 1, no_aplica: 0, futuro: 0, sin_leer: 0 };

const soles = new Intl.NumberFormat("es-PE", { style: "currency", currency: "PEN" });

function fechaIso(valor) {
  if (!valor) return "—";
  const [a, m, d] = valor.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

function situacionFormulario(fila, periodo, periodoTexto, formulario, ultimoConsultable) {
  if (!fila.actualizado_en) return "sin_leer";
  if (periodoTexto > ultimoConsultable) return "futuro";
  if (periodo?.formularios.some((f) => f.formulario === formulario)) return "presentado";
  const desde = fila.obligado_desde[formulario];
  if (!desde || (desde !== "0000-00" && periodoTexto < desde)) return "no_aplica";
  // vence_el llega como medianoche UTC del dia de vencimiento: el mismo dia todavia es "pendiente".
  if (periodo?.vence_el && periodo.vence_el.slice(0, 10) >= hoyPeruIso()) return "pendiente";
  return "no_presentado";
}

function formulariosDe(seleccion) {
  return seleccion === "ambos" ? Object.keys(FORMULARIOS) : [seleccion];
}

function situacionCelda(fila, periodo, periodoTexto, seleccion, ultimoConsultable) {
  return formulariosDe(seleccion)
    .map((f) => situacionFormulario(fila, periodo, periodoTexto, f, ultimoConsultable))
    .reduce((peor, s) => (PESO[s] > PESO[peor] || peor === "sin_leer" || peor === "futuro" ? s : peor));
}

export default function PanelDeclaraciones() {
  const porDefecto = periodoPorDefecto();
  const [anio, setAnio] = useState(porDefecto.anio);
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [seleccion, setSeleccion] = useState("ambos");
  const [mes, setMes] = useState(porDefecto.mes);
  const [filtroEstado, setFiltroEstado] = useState("todas");
  const [busqueda, setBusqueda] = useState("");
  const [digitos, setDigitos] = useState([]);
  const [verNoObligadas, setVerNoObligadas] = useState(false);
  const [encolando, setEncolando] = useState(false);
  const [detalle, setDetalle] = useState(null); // {fila, mes}

  useEffect(() => {
    cargar(anio);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anio]);

  const hayConsultasEnCurso = !!datos?.filas.some((f) => f.consulta_en_curso);
  useEffect(() => {
    if (!hayConsultasEnCurso) return;
    const t = setInterval(() => cargar(anio, { silencioso: true }), 10000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hayConsultasEnCurso, anio]);

  async function cargar(anioPedido, { silencioso = false } = {}) {
    if (!silencioso) setCargando(true);
    try {
      const data = await api.obtenerCumplimientoDeclaraciones(anioPedido);
      setDatos(data);
      setMes((actual) => {
        if (actual) return actual;
        const [a, m] = data.ultimo_periodo_consultable.split("-").map(Number);
        return a === data.anio ? m : 12;
      });
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setCargando(false);
    }
  }

  async function consultarTodas() {
    setEncolando(true);
    setAviso("");
    try {
      const r = await api.consultarDeclaracionesTodas();
      setAviso(
        r.empresas_encoladas
          ? `Se leeran las declaraciones de ${r.empresas_encoladas} empresa(s) en SUNAT, una cada ${r.espaciado_seg} s. La tabla se ira actualizando sola.`
          : "No hay empresas para consultar (todas estan en curso o sin credenciales SOL)."
      );
      cargar(anio, { silencioso: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setEncolando(false);
    }
  }

  async function consultarUna(empresaId) {
    try {
      await api.consultarDeclaraciones(empresaId);
      cargar(anio, { silencioso: true });
    } catch (err) {
      setError(err.message);
    }
  }

  async function cambiarControl(fila, formulario, controlar) {
    const nombre = FORMULARIOS[formulario];
    if (
      !controlar &&
      !window.confirm(
        `${fila.razon_social} dejara de controlarse para ${nombre}: no saldra como "No presentado", no se le crearan tareas y se quitan las que tenga pendientes. ¿Continuar?`
      )
    )
      return;
    try {
      const r = await api.controlarFormularioDeclaracion(fila.empresa_id, formulario, controlar);
      setDetalle(null);
      setAviso(
        controlar
          ? `Listo: se vuelve a controlar ${nombre} de ${fila.razon_social}. Sus tareas se crearan desde el proximo mes.`
          : `Listo: ${fila.razon_social} quedo como no obligada a ${nombre}${r.tareas_borradas ? ` y se quitaron ${r.tareas_borradas} tarea(s) pendiente(s)` : ""}.`
      );
      cargar(anio, { silencioso: true });
    } catch (err) {
      setError(err.message);
    }
  }

  const anioActivo = datos?.anio || new Date().getFullYear();
  const anios = datos?.anios_disponibles?.length ? datos.anios_disponibles : [anioActivo];
  const ultimo = datos?.ultimo_periodo_consultable || "9999-12";
  const periodoTexto = (m) => `${anioActivo}-${String(m).padStart(2, "0")}`;

  const filas = useMemo(() => {
    if (!datos) return [];
    return datos.filas.map((f) => ({
      ...f,
      porMes: Object.fromEntries(f.periodos.map((p) => [Number(p.periodo.slice(5)), p])),
    }));
  }, [datos]);

  // Empresas que no estan obligadas a ninguna de las declaraciones elegidas
  // (p. ej. sin PLAME): no se muestran en el cuadro, salvo que se pida verlas.
  const esNoObligada = (f) => !!f.actualizado_en && formulariosDe(seleccion).every((form) => !f.obligado_desde[form]);
  const filasDelDigito = useMemo(
    () => filas.filter((f) => coincideDigitoRuc(f.ruc, digitos)),
    [filas, digitos]
  );
  const noObligadas = useMemo(
    () => filasDelDigito.filter(esNoObligada),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filasDelDigito, seleccion]
  );
  const filasDelCuadro = useMemo(
    () => (verNoObligadas ? filasDelDigito : filasDelDigito.filter((f) => !esNoObligada(f))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filasDelDigito, verNoObligadas, seleccion]
  );

  const resumen = useMemo(() => {
    const r = { presentado: 0, pendiente: 0, no_presentado: 0, no_aplica: 0, futuro: 0, sin_leer: 0 };
    filasDelCuadro.forEach((f) => (r[situacionCelda(f, f.porMes[mes], periodoTexto(mes || 1), seleccion, ultimo)] += 1));
    return r;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filasDelCuadro, mes, seleccion, ultimo, anioActivo]);

  const filasVisibles = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    return filasDelCuadro.filter((f) => {
      if (q && !f.razon_social.toLowerCase().includes(q) && !f.ruc.includes(q)) return false;
      if (filtroEstado !== "todas" && situacionCelda(f, f.porMes[mes], periodoTexto(mes || 1), seleccion, ultimo) !== filtroEstado) return false;
      return true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filasDelCuadro, busqueda, filtroEstado, mes, seleccion, ultimo, anioActivo]);

  function exportarCsv() {
    descargarCsv(
      `cumplimiento_declaraciones_${seleccion}_${anioActivo}.csv`,
      ["RUC", "Razon social", ...MESES_LARGOS.map((m) => `${m} ${anioActivo}`)],
      filasVisibles.map((f) => [
        f.ruc,
        f.razon_social,
        ...MESES_LARGOS.map((_, i) => ESTILO[situacionCelda(f, f.porMes[i + 1], periodoTexto(i + 1), seleccion, ultimo)].texto),
      ])
    );
  }

  const selectClase =
    "rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-ink focus:border-accent focus:outline-none";

  return (
    <>
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-600">
          Declaraciones mensuales presentadas por cada empresa (IGV-Renta 0621 y PLAME 0601), leidas de SUNAT en
          "Consulta general de declaraciones y pagos". Haz clic en un mes para ver todo lo presentado y pagado. Se
          actualiza sola cada semana y al dia siguiente de cada vencimiento.
        </p>
        <div className="flex items-center gap-2">
          <button
            onClick={exportarCsv}
            disabled={!filasVisibles.length}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition-all duration-300 ease-out hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Download size={15} strokeWidth={1.5} />
            Excel
          </button>
          <button
            onClick={consultarTodas}
            disabled={encolando || hayConsultasEnCurso}
            title="Lee de SUNAT las declaraciones de todas las empresas (una entrada a SUNAT por empresa, espaciadas)"
            className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-bold text-white transition-all duration-300 ease-out hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
          >
            {encolando || hayConsultasEnCurso ? (
              <Loader2 size={15} strokeWidth={2} className="animate-spin" />
            ) : (
              <RefreshCw size={15} strokeWidth={2} />
            )}
            {hayConsultasEnCurso ? "Consultando SUNAT..." : "Consultar todas en SUNAT"}
          </button>
        </div>
      </div>

      {error && <div className="mt-5 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>}
      {aviso && <div className="mt-5 rounded-lg border border-sky-100 bg-sky-50 px-3 py-2.5 text-sm text-sky-700">{aviso}</div>}

      <div className="mt-5 flex flex-wrap items-end gap-3">
        <label className="text-xs font-semibold text-slate-500">
          Año
          <select value={anioActivo} onChange={(e) => { setAnio(Number(e.target.value)); setMes(null); }} className={`${selectClase} ml-2`}>
            {anios.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label className="text-xs font-semibold text-slate-500">
          Periodo
          <select value={mes || ""} onChange={(e) => setMes(Number(e.target.value))} className={`${selectClase} ml-2`}>
            {MESES_LARGOS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
          </select>
          {anioActivo === porDefecto.anio && mes === porDefecto.mes ? (
            <span className="ml-2 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">Vence este mes</span>
          ) : (
            <button
              type="button"
              onClick={() => { setAnio(porDefecto.anio); setMes(porDefecto.mes); }}
              className="ml-2 text-[11px] font-semibold text-accent hover:underline"
            >
              Ir al periodo que vence este mes
            </button>
          )}
        </label>
        <label className="text-xs font-semibold text-slate-500">
          Declaracion
          <select value={seleccion} onChange={(e) => setSeleccion(e.target.value)} className={`${selectClase} ml-2`}>
            {OPCIONES_FORMULARIO.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </label>
        <div className="relative ml-auto">
          <Search size={14} strokeWidth={1.75} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar empresa o RUC"
            className="w-64 rounded-lg border border-slate-200 bg-white py-1.5 pl-8 pr-3 text-sm text-ink focus:border-accent focus:outline-none"
          />
        </div>
      </div>
      <div className="mt-3">
        <FiltroDigitoRuc digitos={digitos} onCambio={setDigitos} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {["no_presentado", "pendiente", "presentado", "no_aplica"].map((s) => {
          const { texto, chip, Icon } = ESTILO[s];
          const activo = filtroEstado === s;
          return (
            <button
              key={s}
              onClick={() => setFiltroEstado(activo ? "todas" : s)}
              className={`surface-card flex items-center justify-between p-4 text-left transition-all duration-300 ease-out hover:-translate-y-0.5 ${
                activo ? "ring-2 ring-accent" : ""
              }`}
            >
              <div>
                <p className="text-xs font-semibold text-slate-500">
                  {texto} · {MESES_LARGOS[(mes || 1) - 1]} {anioActivo}
                </p>
                <p className="mt-1 text-2xl font-extrabold text-ink">{resumen[s]}</p>
              </div>
              <span className={`flex h-9 w-9 items-center justify-center rounded-full ${chip}`}>
                {Icon ? <Icon size={17} strokeWidth={2} /> : "—"}
              </span>
            </button>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap gap-1">
        {FILTROS_ESTADO.map((f) => (
          <button
            key={f.id}
            onClick={() => setFiltroEstado(f.id)}
            className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
              filtroEstado === f.id ? "bg-accent text-white" : "bg-white text-slate-600 hover:bg-slate-100"
            }`}
          >
            {f.label}
          </button>
        ))}
        <span className="ml-2 self-center text-xs text-slate-500">
          {filasVisibles.length} de {filasDelCuadro.length} empresas · filtro aplicado a {MESES_LARGOS[(mes || 1) - 1]}
        </span>
        {noObligadas.length > 0 && (
          <button
            type="button"
            onClick={() => setVerNoObligadas((v) => !v)}
            className="ml-auto self-center text-xs font-semibold text-accent hover:underline"
          >
            {verNoObligadas
              ? `Ocultar las ${noObligadas.length} empresa(s) no obligadas`
              : `Ver ${noObligadas.length} empresa(s) no obligadas a ${seleccion === "ambos" ? "estas declaraciones" : FORMULARIOS[seleccion]}`}
          </button>
        )}
      </div>

      <div className="surface-card mt-4 overflow-x-auto">
        {cargando ? (
          <p className="p-6 text-sm text-slate-500">Cargando...</p>
        ) : !filas.length ? (
          <p className="p-6 text-sm text-slate-500">No hay empresas activas para mostrar.</p>
        ) : (
          <table className="w-full min-w-[960px] border-collapse text-sm">
            <thead>
              <tr className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <th className="sticky left-0 z-10 bg-slate-50 px-4 py-3 text-left">Empresa / RUC</th>
                {MESES_CORTOS.map((m, i) => (
                  <th
                    key={m}
                    onClick={() => setMes(i + 1)}
                    className={`cursor-pointer px-1 py-3 text-center ${mes === i + 1 ? "bg-accent-light text-accent" : "hover:text-ink"}`}
                  >
                    {m}
                  </th>
                ))}
                <th className="px-3 py-3 text-right">Lectura</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filasVisibles.map((f) => (
                <tr key={f.empresa_id} className="hover:bg-slate-50/60">
                  <td className="sticky left-0 z-10 max-w-[260px] bg-white px-4 py-2.5">
                    <Link href={`/empresas/${f.empresa_id}`} className="block truncate font-semibold text-ink hover:text-accent" title={f.razon_social}>
                      {f.razon_social}
                    </Link>
                    <span className="text-xs text-slate-500">{f.ruc}</span>
                  </td>
                  {MESES_LARGOS.map((nombreMes, i) => {
                    const p = f.porMes[i + 1];
                    const s = situacionCelda(f, p, periodoTexto(i + 1), seleccion, ultimo);
                    const { celda, Icon, texto } = ESTILO[s];
                    const rectificadas = formulariosDe(seleccion).some(
                      (form) => (p?.formularios.filter((x) => x.formulario === form).length || 0) > 1
                    );
                    const clicable = !!f.actualizado_en && s !== "futuro";
                    return (
                      <td
                        key={nombreMes}
                        onClick={() => clicable && setDetalle({ fila: f, mes: i + 1 })}
                        title={`${nombreMes} ${anioActivo}: ${texto}${rectificadas ? " (con rectificatoria)" : ""}`}
                        className={`relative px-1 py-2.5 text-center ${celda} ${clicable ? "cursor-pointer hover:brightness-95" : ""} ${
                          mes === i + 1 ? "ring-1 ring-inset ring-accent/40" : ""
                        }`}
                      >
                        {Icon ? <Icon size={16} strokeWidth={2} className="mx-auto" /> : "—"}
                        {rectificadas && <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-violet-500" />}
                      </td>
                    );
                  })}
                  <td className="whitespace-nowrap px-3 py-2.5 text-right text-xs text-slate-500">
                    <div className="flex items-center justify-end gap-2">
                      {f.ultimo_error && (
                        <span title={`Ultima lectura fallida: ${f.ultimo_error}`}>
                          <AlertTriangle size={14} strokeWidth={2} className="text-amber-500" />
                        </span>
                      )}
                      <span>{f.actualizado_en ? fechaPeru(f.actualizado_en) : "Sin leer"}</span>
                      <button
                        onClick={() => consultarUna(f.empresa_id)}
                        disabled={f.consulta_en_curso}
                        title="Leer las declaraciones de esta empresa en SUNAT"
                        className="flex items-center justify-center rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-accent disabled:cursor-not-allowed"
                      >
                        {f.consulta_en_curso ? (
                          <Loader2 size={14} strokeWidth={2} className="animate-spin text-accent" />
                        ) : (
                          <RefreshCw size={14} strokeWidth={2} />
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-slate-500">
        {["presentado", "pendiente", "no_presentado", "no_aplica"].map((s) => {
          const { texto, chip, Icon } = ESTILO[s];
          return (
            <span key={s} className="flex items-center gap-1.5">
              <span className={`flex h-5 w-5 items-center justify-center rounded-full ${chip}`}>
                {Icon ? <Icon size={12} strokeWidth={2} /> : "—"}
              </span>
              {texto}
              {s === "pendiente" && " (aun en plazo)"}
            </span>
          );
        })}
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-violet-500" />
          Tiene rectificatoria
        </span>
      </div>

      {detalle && (
        <PanelDetallePeriodo
          fila={detalle.fila}
          periodo={detalle.fila.porMes[detalle.mes]}
          periodoTexto={periodoTexto(detalle.mes)}
          nombrePeriodo={`${MESES_LARGOS[detalle.mes - 1]} ${anioActivo}`}
          ultimo={ultimo}
          onCambiarControl={(formulario, controlar) => cambiarControl(detalle.fila, formulario, controlar)}
          onCerrar={() => setDetalle(null)}
        />
      )}
    </>
  );
}

// Detalle de un mes de una empresa: estado de cada declaracion controlada y
// todo lo que SUNAT lista para ese periodo (declaraciones y pagos).
function PanelDetallePeriodo({ fila, periodo, periodoTexto, nombrePeriodo, ultimo, onCambiarControl, onCerrar }) {
  useEffect(() => {
    function alTeclear(e) {
      if (e.key === "Escape") onCerrar();
    }
    window.addEventListener("keydown", alTeclear);
    return () => window.removeEventListener("keydown", alTeclear);
  }, [onCerrar]);

  const formularios = periodo?.formularios || [];
  const totalPagado = formularios.reduce((s, f) => s + f.importe_pagado, 0);
  const vistos = {};

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink/40" onClick={onCerrar}>
      <div className="flex h-full w-full max-w-lg flex-col bg-white shadow-soft-lg animate-fade-in-up" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-6 py-5">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Periodo {nombrePeriodo}</p>
            <h2 className="mt-1 truncate text-lg font-bold text-ink">{fila.razon_social}</h2>
            <p className="text-xs text-slate-500">RUC {fila.ruc}</p>
          </div>
          <button onClick={onCerrar} className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-ink" aria-label="Cerrar">
            <X size={18} strokeWidth={1.75} />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(FORMULARIOS).map(([codigo, nombre]) => {
              const s = situacionFormulario(fila, periodo, periodoTexto, codigo, ultimo);
              const { texto, chip, Icon } = ESTILO[s];
              const apagado = fila.formularios_no_controlados?.includes(codigo);
              return (
                <div key={codigo} className="rounded-xl border border-slate-100 p-3">
                  <p className="text-xs font-semibold text-slate-500">{nombre}</p>
                  <span className={`mt-1.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-bold ${chip}`}>
                    {Icon && <Icon size={12} strokeWidth={2} />}
                    {apagado ? "No obligada" : texto}
                  </span>
                  <button
                    type="button"
                    onClick={() => onCambiarControl(codigo, apagado)}
                    className="mt-2 block text-[11px] font-semibold text-slate-500 underline-offset-2 hover:text-accent hover:underline"
                  >
                    {apagado ? "Volver a controlar" : "No esta obligada"}
                  </button>
                </div>
              );
            })}
          </div>
          {periodo?.vence_el && (
            <p className="text-xs text-slate-500">
              Vencimiento segun el cronograma de SUNAT: <strong>{fechaIso(periodo.vence_el)}</strong>
            </p>
          )}

          <div>
            <div className="flex items-center justify-between">
              <p className="text-xs font-bold uppercase tracking-wide text-slate-500">Presentado en SUNAT</p>
              {totalPagado > 0 && <p className="text-xs text-slate-500">Total pagado: <strong className="text-ink">{soles.format(totalPagado)}</strong></p>}
            </div>
            {!formularios.length ? (
              <p className="mt-3 rounded-lg bg-slate-50 p-4 text-sm text-slate-500">SUNAT no registra declaraciones ni pagos para este periodo.</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {formularios.map((f) => {
                  vistos[f.formulario] = (vistos[f.formulario] || 0) + 1;
                  const esRectificatoria = FORMULARIOS[f.formulario] && vistos[f.formulario] > 1;
                  return (
                    <li key={`${f.formulario}-${f.num_orden}-${f.cod_tributo}`} className="rounded-xl border border-slate-100 p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="flex items-center gap-1.5 text-sm font-semibold text-ink">
                            <FileText size={14} strokeWidth={1.75} className="shrink-0 text-slate-400" />
                            <span className="truncate">{f.descripcion || `Formulario ${f.formulario}`}</span>
                          </p>
                          <p className="mt-0.5 text-xs text-slate-500">
                            Form. {f.formulario} · N° orden {f.num_orden}
                            {f.cod_tributo && ` · Tributo ${f.cod_tributo}`}
                          </p>
                          <p className="mt-0.5 text-xs text-slate-500">
                            Presentado el {fechaIso(f.fecha_presentacion)}
                            {f.banco && ` · ${f.banco}`}
                          </p>
                          {esRectificatoria && (
                            <span className="mt-1 inline-block rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-bold uppercase text-violet-700">
                              Rectificatoria / sustitutoria
                            </span>
                          )}
                        </div>
                        {f.importe_pagado > 0 && <span className="shrink-0 text-sm font-bold text-ink">{soles.format(f.importe_pagado)}</span>}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
