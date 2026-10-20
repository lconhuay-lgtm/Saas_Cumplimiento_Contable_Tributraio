"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Download,
  Loader2,
  RefreshCw,
  Search,
  XCircle,
} from "lucide-react";
import { api } from "../../lib/api";
import { descargarCsv, periodoPorDefecto } from "./utilidades";

const MESES_CORTOS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Set", "Oct", "Nov", "Dic"];
const MESES_LARGOS = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Setiembre", "Octubre", "Noviembre", "Diciembre",
];

const OPCIONES_LIBRO = [
  { id: "ambos", label: "Ventas y Compras" },
  { id: "rvie", label: "Ventas (RVIE)" },
  { id: "rce", label: "Compras (RCE)" },
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
};
const PESO = { no_presentado: 3, pendiente: 2, presentado: 1, no_aplica: 0 };

function situacionLibro(estado, venceEl) {
  if (!estado) return "no_aplica";
  if (estado.presentado) return "presentado";
  // vence_el llega como medianoche UTC del dia de vencimiento: se compara
  // solo la fecha contra el dia local, para que el mismo dia todavia sea
  // "pendiente" y no "no presentado".
  if (venceEl && venceEl.slice(0, 10) >= new Date().toLocaleDateString("en-CA")) return "pendiente";
  return "no_presentado";
}

function situacionCelda(periodo, libro) {
  if (!periodo) return "no_aplica";
  const libros = libro === "ambos" ? ["rvie", "rce"] : [libro];
  return libros
    .map((l) => situacionLibro(periodo[l], periodo.vence_el))
    .reduce((peor, s) => (PESO[s] > PESO[peor] ? s : peor), "no_aplica");
}

function fechaCorta(valor) {
  return new Date(valor).toLocaleDateString("es-PE", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" });
}

function detalleCelda(periodo, nombreMes, anio) {
  if (!periodo) return `${nombreMes} ${anio}: SUNAT no lista este periodo (sin obligacion SIRE o aun no corresponde)`;
  const partes = [`${nombreMes} ${anio}`];
  partes.push(`Ventas: ${ESTILO[situacionLibro(periodo.rvie, periodo.vence_el)].texto}`);
  partes.push(`Compras: ${ESTILO[situacionLibro(periodo.rce, periodo.vence_el)].texto}`);
  if (periodo.vence_el) partes.push(`Vence: ${fechaCorta(periodo.vence_el)}`);
  return partes.join(" · ");
}

export default function PanelSire() {
  const porDefecto = periodoPorDefecto();
  const [anio, setAnio] = useState(porDefecto.anio);
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [libro, setLibro] = useState("ambos");
  const [mes, setMes] = useState(porDefecto.mes);
  const [filtroEstado, setFiltroEstado] = useState("todas");
  const [busqueda, setBusqueda] = useState("");
  const [encolando, setEncolando] = useState(false);

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
      const data = await api.obtenerCumplimientoSire(anioPedido);
      setDatos(data);
      setMes((actual) => {
        if (actual) return actual;
        const meses = data.filas.flatMap((f) => f.periodos.map((p) => Number(p.periodo.slice(5))));
        return meses.length ? Math.max(...meses) : new Date().getMonth() + 1;
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
      const r = await api.consultarSireTodas();
      setAviso(
        r.empresas_encoladas
          ? `Se leera el SIRE de ${r.empresas_encoladas} empresa(s) en SUNAT, una cada ${r.espaciado_seg} s. La tabla se ira actualizando sola.`
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
      await api.consultarSire(empresaId);
      cargar(anio, { silencioso: true });
    } catch (err) {
      setError(err.message);
    }
  }

  const anioActivo = datos?.anio || new Date().getFullYear();
  const anios = datos?.anios_disponibles?.length ? datos.anios_disponibles : [anioActivo];

  const filas = useMemo(() => {
    if (!datos) return [];
    return datos.filas.map((f) => ({
      ...f,
      porMes: Object.fromEntries(f.periodos.map((p) => [Number(p.periodo.slice(5)), p])),
    }));
  }, [datos]);

  const resumen = useMemo(() => {
    const r = { presentado: 0, pendiente: 0, no_presentado: 0, no_aplica: 0 };
    filas.forEach((f) => (r[situacionCelda(f.porMes[mes], libro)] += 1));
    return r;
  }, [filas, mes, libro]);

  const filasVisibles = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    return filas.filter((f) => {
      if (q && !f.razon_social.toLowerCase().includes(q) && !f.ruc.includes(q)) return false;
      if (filtroEstado !== "todas" && situacionCelda(f.porMes[mes], libro) !== filtroEstado) return false;
      return true;
    });
  }, [filas, busqueda, filtroEstado, mes, libro]);

  function exportarCsv() {
    descargarCsv(
      `cumplimiento_sire_${libro}_${anioActivo}.csv`,
      ["RUC", "Razon social", ...MESES_LARGOS.map((m) => `${m} ${anioActivo}`)],
      filasVisibles.map((f) => [
        f.ruc,
        f.razon_social,
        ...MESES_LARGOS.map((_, i) => ESTILO[situacionCelda(f.porMes[i + 1], libro)].texto),
      ])
    );
  }

  const selectClase =
    "rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-ink focus:border-accent focus:outline-none";

  return (
    <>
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-600">
          Presentacion de los Registros Electronicos (SIRE) de cada empresa, leido directamente de SUNAT. Se actualiza
          solo cada semana y al dia siguiente de cada vencimiento.
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
            title="Lee de SUNAT el estado del SIRE de todas las empresas (una entrada a SUNAT por empresa, espaciadas)"
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
          Registro
          <select value={libro} onChange={(e) => setLibro(e.target.value)} className={`${selectClase} ml-2`}>
            {OPCIONES_LIBRO.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
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
          {filasVisibles.length} de {filas.length} empresas · filtro aplicado a {MESES_LARGOS[(mes || 1) - 1]}
        </span>
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
                    const s = situacionCelda(p, libro);
                    const { celda, Icon } = ESTILO[s];
                    return (
                      <td
                        key={nombreMes}
                        title={detalleCelda(p, nombreMes, anioActivo)}
                        className={`px-1 py-2.5 text-center ${celda} ${mes === i + 1 ? "ring-1 ring-inset ring-accent/40" : ""}`}
                      >
                        {Icon ? <Icon size={16} strokeWidth={2} className="mx-auto" /> : "—"}
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
                      <span>{f.actualizado_en ? new Date(f.actualizado_en).toLocaleDateString("es-PE") : "Sin leer"}</span>
                      <button
                        onClick={() => consultarUna(f.empresa_id)}
                        disabled={f.consulta_en_curso}
                        title="Leer el SIRE de esta empresa en SUNAT"
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
              {s === "no_aplica" && " (sin obligacion SIRE)"}
            </span>
          );
        })}
        <span>· Con "Ventas y Compras", la celda muestra el peor de los dos.</span>
      </div>
    </>
  );
}
