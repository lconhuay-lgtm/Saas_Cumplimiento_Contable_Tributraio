"use client";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  AlertTriangle,
  Building2,
  CalendarClock,
  CheckCheck,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock,
  Flag,
  History,
  ListChecks,
  Loader2,
  MinusCircle,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import Sidebar from "../../components/Sidebar";
import ConfirmDialog from "../../components/ConfirmDialog";
import { api, getToken } from "../../lib/api";

const ETIQUETAS_TIPO = {
  igv_renta: "IGV-Renta",
  planilla: "Planilla",
  afp: "AFP",
  sbs: "Reporte SBS",
  cts: "CTS",
  itan: "ITAN",
  sire: "SIRE",
  otro: "Otro",
};

// Un punto de color por tipo (en vez de una etiqueta grande) -- deja que el
// titulo y la fecha sean lo que mas se lee en cada fila.
const PUNTO_TIPO = {
  igv_renta: "bg-emerald-500",
  planilla: "bg-accent",
  afp: "bg-violet-500",
  sbs: "bg-amber-500",
  cts: "bg-sky-500",
  itan: "bg-rose-500",
  sire: "bg-cyan-500",
  otro: "bg-slate-400",
};

const PRIORIDADES = [
  { valor: "baja", etiqueta: "Baja", color: "text-slate-400" },
  { valor: "media", etiqueta: "Media", color: "text-sky-500" },
  { valor: "alta", etiqueta: "Alta", color: "text-amber-500" },
  { valor: "urgente", etiqueta: "Urgente", color: "text-red-600" },
];
const COLOR_PRIORIDAD = Object.fromEntries(PRIORIDADES.map((p) => [p.valor, p.color]));

const PESTANAS = [
  { valor: "pendiente", etiqueta: "Pendientes" },
  { valor: "completado", etiqueta: "Completadas" },
  { valor: "no_aplica", etiqueta: "No aplica" },
  { valor: "", etiqueta: "Todas" },
];

// Las pendientes se agrupan por urgencia (como Todoist/Linear) en vez de una
// lista plana paginada: lo vencido arriba, despues hoy, la semana, etc.
const GRUPOS = [
  { id: "vencidas", etiqueta: "Vencidas", punto: "bg-red-500", texto: "text-red-600" },
  { id: "hoy", etiqueta: "Vencen hoy", punto: "bg-amber-500", texto: "text-amber-600" },
  { id: "semana", etiqueta: "Proximos 7 dias", punto: "bg-sky-500", texto: "text-sky-600" },
  { id: "despues", etiqueta: "Mas adelante", punto: "bg-slate-300", texto: "text-slate-500" },
  { id: "sin_fecha", etiqueta: "Sin fecha", punto: "bg-slate-200", texto: "text-slate-400" },
];
const VISIBLES_POR_GRUPO = 8;

function formatoFecha(fechaIso) {
  if (!fechaIso) return null;
  return new Date(fechaIso).toLocaleDateString("es-PE", { timeZone: "UTC", day: "2-digit", month: "short", year: "numeric" });
}

function diasRestantes(fechaIso) {
  if (!fechaIso) return null;
  const hoy = new Date();
  hoy.setUTCHours(0, 0, 0, 0);
  const fecha = new Date(fechaIso);
  fecha.setUTCHours(0, 0, 0, 0);
  return Math.round((fecha - hoy) / 86400000);
}

function grupoDe(tarea) {
  const dias = diasRestantes(tarea.fecha_vencimiento);
  if (dias == null) return "sin_fecha";
  if (dias < 0) return "vencidas";
  if (dias === 0) return "hoy";
  if (dias <= 7) return "semana";
  return "despues";
}

function sumarMeses(fechaIsoODia, meses) {
  const base = fechaIsoODia ? new Date(`${fechaIsoODia.slice(0, 10)}T00:00:00`) : new Date();
  base.setMonth(base.getMonth() + meses);
  return base.toISOString().slice(0, 10);
}

function sumarDias(fechaIsoODia, dias) {
  const base = fechaIsoODia ? new Date(`${fechaIsoODia.slice(0, 10)}T00:00:00`) : new Date();
  base.setDate(base.getDate() + dias);
  return base.toISOString().slice(0, 10);
}

function textoVencimiento(tarea) {
  const dias = diasRestantes(tarea.fecha_vencimiento);
  if (dias == null) return { texto: "Sin fecha", clase: "bg-slate-100 text-slate-500" };
  if (tarea.estado !== "pendiente") return { texto: formatoFecha(tarea.fecha_vencimiento), clase: "bg-slate-100 text-slate-500" };
  if (dias < 0) return { texto: `Vencio hace ${Math.abs(dias)} d`, clase: "bg-red-50 text-red-700" };
  if (dias === 0) return { texto: "Vence hoy", clase: "bg-amber-50 text-amber-700" };
  if (dias === 1) return { texto: "Vence manana", clase: "bg-amber-50 text-amber-700" };
  if (dias <= 7) return { texto: `En ${dias} dias`, clase: "bg-sky-50 text-sky-700" };
  return { texto: formatoFecha(tarea.fecha_vencimiento), clase: "bg-slate-100 text-slate-600" };
}

// useSearchParams() exige un limite de Suspense en el build de produccion
// (next build) -- mismo fix que empresas/page.js (Fase R4).
export default function TareasPage() {
  return (
    <Suspense fallback={null}>
      <TareasPageContenido />
    </Suspense>
  );
}

function TareasPageContenido() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // El Dashboard enlaza aca con ?estado=vencida (o aplazada) para llegar
  // directo a esas tareas: ahora son un filtro dentro de "Pendientes".
  const estadoInicial = searchParams.get("estado");
  const [pestana, setPestana] = useState(
    estadoInicial && PESTANAS.some((p) => p.valor === estadoInicial) ? estadoInicial : "pendiente"
  );
  const [soloGrupo, setSoloGrupo] = useState(estadoInicial === "vencida" ? "vencidas" : null);
  const [soloAplazadas, setSoloAplazadas] = useState(estadoInicial === "aplazada");
  const [busqueda, setBusqueda] = useState("");
  const [filtroTipo, setFiltroTipo] = useState("");
  // Cartera: "" = todas, "yo" = solo las de mi cartera, o el id de otro usuario del tenant.
  const [filtroAsignado, setFiltroAsignado] = useState("");

  const [pendientes, setPendientes] = useState([]);
  const [otras, setOtras] = useState([]);
  const [avance, setAvance] = useState(null);
  const [empresas, setEmpresas] = useState([]);
  const [usuarios, setUsuarios] = useState([]);
  const [miUsuarioId, setMiUsuarioId] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [generando, setGenerando] = useState(false);
  const [panel, setPanel] = useState(null); // {modo: "nueva"} | {modo: "editar", tarea} | null
  const [modoSeleccion, setModoSeleccion] = useState(false);
  const [seleccionadas, setSeleccionadas] = useState(new Set());
  const [procesandoMasivo, setProcesandoMasivo] = useState(false);
  const [aviso, setAviso] = useState(null); // {texto, deshacer?}
  const temporizadorAviso = useRef(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api.listarEmpresas().then(setEmpresas).catch(() => {});
    api.me().then((yo) => setMiUsuarioId(yo.id)).catch(() => {});
    api.listarUsuarios().then(setUsuarios).catch(() => {});
    api.obtenerAvanceCumplimiento().then(setAvance).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    cargarTareas();
    setSeleccionadas(new Set());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pestana, filtroAsignado, miUsuarioId]);

  useEffect(() => () => clearTimeout(temporizadorAviso.current), []);

  function filtrosCartera() {
    if (filtroAsignado === "yo" && miUsuarioId) return { asignadoAUsuarioId: miUsuarioId };
    if (filtroAsignado && filtroAsignado !== "yo") return { asignadoAUsuarioId: filtroAsignado };
    return {};
  }

  async function cargarTareas({ silencioso = false } = {}) {
    if (!silencioso) setCargando(true);
    setError("");
    try {
      const cartera = filtrosCartera();
      // Las pendientes se piden siempre: alimentan los indicadores de arriba
      // aunque se este mirando otra pestana.
      const [listaPendientes, listaOtras] = await Promise.all([
        api.listarTareas({ ...cartera, estado: "pendiente" }),
        pestana === "pendiente" ? Promise.resolve([]) : api.listarTareas({ ...cartera, estado: pestana || undefined }),
      ]);
      setPendientes(listaPendientes);
      setOtras(listaOtras);
    } catch (err) {
      setError(err.message);
    } finally {
      setCargando(false);
    }
  }

  function mostrarAviso(texto, deshacer = null) {
    clearTimeout(temporizadorAviso.current);
    setAviso({ texto, deshacer });
    temporizadorAviso.current = setTimeout(() => setAviso(null), 6000);
  }

  // Completar es de un clic y se refleja al instante; si el servidor falla
  // se revierte. El aviso de abajo permite deshacerlo.
  async function cambiarEstado(tarea, nuevoEstado, { avisar = true } = {}) {
    const reemplazar = (lista) => lista.map((t) => (t.id === tarea.id ? { ...t, estado: nuevoEstado } : t));
    setPendientes(reemplazar);
    setOtras(reemplazar);
    try {
      await api.actualizarTarea(tarea.id, { estado: nuevoEstado });
      if (avisar && nuevoEstado === "completado") {
        mostrarAviso(`"${tarea.titulo}" completada`, () => cambiarEstado(tarea, "pendiente", { avisar: false }));
      }
      cargarTareas({ silencioso: true });
      api.obtenerAvanceCumplimiento().then(setAvance).catch(() => {});
    } catch (err) {
      cargarTareas({ silencioso: true });
      alert(err.message);
    }
  }

  async function aplazarUnMes(tarea) {
    try {
      const nueva = sumarMeses(tarea.fecha_vencimiento, 1);
      await api.actualizarTarea(tarea.id, { fecha_vencimiento: new Date(nueva).toISOString() });
      mostrarAviso(`"${tarea.titulo}" se aplazo al ${formatoFecha(new Date(nueva).toISOString())}`);
      cargarTareas({ silencioso: true });
    } catch (err) {
      alert(err.message);
    }
  }

  async function generarDelMes() {
    setGenerando(true);
    try {
      const hoy = new Date();
      const r = await api.generarTareas(hoy.getFullYear(), hoy.getMonth() + 1);
      mostrarAviso(
        r.tareas_creadas === 0
          ? "No hay tareas nuevas para este mes (ya estaban creadas o no hay obligaciones configuradas)."
          : `Se generaron ${r.tareas_creadas} tarea(s) nueva(s) del periodo ${r.periodo}.`
      );
      await cargarTareas({ silencioso: true });
    } catch (err) {
      alert(err.message);
    } finally {
      setGenerando(false);
    }
  }

  function alternarSeleccion(id) {
    setSeleccionadas((prev) => {
      const copia = new Set(prev);
      if (copia.has(id)) copia.delete(id);
      else copia.add(id);
      return copia;
    });
  }

  async function aplicarASeleccionadas(cambio, textoHecho) {
    if (seleccionadas.size === 0) return;
    setProcesandoMasivo(true);
    try {
      const ids = [...seleccionadas];
      const resultados = await Promise.allSettled(ids.map((id) => api.actualizarTarea(id, cambio)));
      const fallidas = resultados.filter((r) => r.status === "rejected").length;
      setSeleccionadas(new Set());
      setModoSeleccion(false);
      await cargarTareas({ silencioso: true });
      api.obtenerAvanceCumplimiento().then(setAvance).catch(() => {});
      mostrarAviso(
        fallidas > 0
          ? `${ids.length - fallidas} de ${ids.length} tareas ${textoHecho}. ${fallidas} fallaron, intenta de nuevo con esas.`
          : `${ids.length} tarea(s) ${textoHecho}.`
      );
    } finally {
      setProcesandoMasivo(false);
    }
  }

  const listaBase = pestana === "pendiente" ? pendientes : otras;

  const tiposPresentes = useMemo(
    () => Array.from(new Set([...pendientes, ...otras].map((t) => t.tipo))).filter(Boolean),
    [pendientes, otras]
  );

  const filtradas = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    return listaBase.filter((t) => {
      if (q && !`${t.titulo} ${t.empresa_razon_social} ${t.empresa_ruc}`.toLowerCase().includes(q)) return false;
      if (filtroTipo && t.tipo !== filtroTipo) return false;
      if (pestana === "pendiente" && soloAplazadas && !t.aplazada) return false;
      if (pestana === "pendiente" && soloGrupo === "vencidas" && grupoDe(t) !== "vencidas") return false;
      if (pestana === "pendiente" && soloGrupo === "semana" && !["hoy", "semana"].includes(grupoDe(t))) return false;
      return true;
    });
  }, [listaBase, busqueda, filtroTipo, soloAplazadas, soloGrupo, pestana]);

  const indicadores = useMemo(() => {
    const r = { vencidas: 0, semana: 0, total: pendientes.length };
    pendientes.forEach((t) => {
      const g = grupoDe(t);
      if (g === "vencidas") r.vencidas += 1;
      if (g === "hoy" || g === "semana") r.semana += 1;
    });
    return r;
  }, [pendientes]);

  const porGrupo = useMemo(() => {
    const grupos = Object.fromEntries(GRUPOS.map((g) => [g.id, []]));
    filtradas.forEach((t) => grupos[grupoDe(t)].push(t));
    Object.values(grupos).forEach((lista) =>
      lista.sort((a, b) => new Date(a.fecha_vencimiento || 0) - new Date(b.fecha_vencimiento || 0))
    );
    return grupos;
  }, [filtradas]);

  const otrasOrdenadas = useMemo(
    () =>
      [...filtradas].sort(
        (a, b) =>
          new Date(b.fecha_completado || b.fecha_vencimiento || b.creado_en) -
          new Date(a.fecha_completado || a.fecha_vencimiento || a.creado_en)
      ),
    [filtradas]
  );

  const avancePct = avance?.total ? Math.round(avance.total.avance) : null;
  const hayFiltros = busqueda || filtroTipo || soloAplazadas || soloGrupo;

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 pb-28 pt-24 xl:px-12">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-ink">Tareas</h1>
            <p className="mt-1 text-sm text-slate-600">Tu agenda de obligaciones por empresa, ordenada por urgencia</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={generarDelMes}
              disabled={generando}
              title="Crea las tareas del mes actual a partir de las obligaciones configuradas en cada empresa"
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-all duration-300 ease-out hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {generando ? <Loader2 size={15} strokeWidth={1.75} className="animate-spin" /> : <RefreshCw size={15} strokeWidth={1.75} />}
              Generar tareas del mes
            </button>
            <button
              onClick={() => setPanel({ modo: "nueva" })}
              className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark"
            >
              <Plus size={15} strokeWidth={2} />
              Nueva tarea
            </button>
          </div>
        </div>

        {/* Indicadores: ademas de informar, filtran la lista con un clic. */}
        <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <TarjetaIndicador
            titulo="Vencidas"
            valor={indicadores.vencidas}
            nota={indicadores.vencidas ? "requieren atencion" : "nada vencido"}
            Icono={AlertTriangle}
            tono={indicadores.vencidas ? "rojo" : "neutro"}
            activa={pestana === "pendiente" && soloGrupo === "vencidas"}
            onClick={() => {
              setPestana("pendiente");
              setSoloGrupo(soloGrupo === "vencidas" ? null : "vencidas");
            }}
          />
          <TarjetaIndicador
            titulo="Vencen en 7 dias"
            valor={indicadores.semana}
            nota="incluye las de hoy"
            Icono={CalendarClock}
            tono={indicadores.semana ? "ambar" : "neutro"}
            activa={pestana === "pendiente" && soloGrupo === "semana"}
            onClick={() => {
              setPestana("pendiente");
              setSoloGrupo(soloGrupo === "semana" ? null : "semana");
            }}
          />
          <TarjetaIndicador
            titulo="Pendientes"
            valor={indicadores.total}
            nota="en total"
            Icono={ListChecks}
            tono="neutro"
            activa={pestana === "pendiente" && !soloGrupo}
            onClick={() => {
              setPestana("pendiente");
              setSoloGrupo(null);
            }}
          />
          <div className="surface-card p-4">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold text-slate-500">
                Avance {avance?.periodo ? `del periodo ${avance.periodo}` : "del periodo"}
              </p>
              <CheckCheck size={16} strokeWidth={1.75} className="text-emerald-500" />
            </div>
            <p className="mt-1 text-2xl font-extrabold text-ink">{avancePct != null ? `${avancePct}%` : "—"}</p>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-emerald-500 transition-all duration-500" style={{ width: `${avancePct || 0}%` }} />
            </div>
            {avance?.total && (
              <p className="mt-1.5 text-xs text-slate-500">
                {avance.total.completados} de {avance.total.total} completadas
              </p>
            )}
          </div>
        </div>

        {/* Pestanas + filtros en una sola barra. */}
        <div className="mt-6 flex flex-wrap items-center gap-3 border-b border-slate-200">
          <div className="flex gap-1">
            {PESTANAS.map((p) => (
              <button
                key={p.valor || "todas"}
                onClick={() => {
                  setPestana(p.valor);
                  setSoloGrupo(null);
                  setSoloAplazadas(false);
                }}
                className={`-mb-px border-b-2 px-3 py-2.5 text-sm font-semibold transition-colors ${
                  pestana === p.valor ? "border-accent text-accent" : "border-transparent text-slate-500 hover:text-ink"
                }`}
              >
                {p.etiqueta}
                {p.valor === "pendiente" && (
                  <span className="ml-1.5 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold text-slate-600">
                    {pendientes.length}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search size={14} strokeWidth={1.75} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
              placeholder="Buscar tarea, empresa o RUC"
              className="w-64 rounded-lg border border-slate-200 bg-white py-1.5 pl-8 pr-3 text-sm text-ink focus:border-accent focus:outline-none"
            />
          </div>
          <select
            value={filtroTipo}
            onChange={(e) => setFiltroTipo(e.target.value)}
            className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-600 focus:border-accent focus:outline-none"
          >
            <option value="">Todos los tipos</option>
            {tiposPresentes.map((t) => (
              <option key={t} value={t}>
                {ETIQUETAS_TIPO[t] || t}
              </option>
            ))}
          </select>
          <select
            value={filtroAsignado}
            onChange={(e) => setFiltroAsignado(e.target.value)}
            title="Cartera: filtrar por quien tiene asignada la empresa de cada tarea"
            className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-600 focus:border-accent focus:outline-none"
          >
            <option value="">Todas las carteras</option>
            <option value="yo">Mi cartera</option>
            {usuarios.filter((u) => u.id !== miUsuarioId).map((u) => (
              <option key={u.id} value={u.id}>
                {u.email}
              </option>
            ))}
          </select>
          {pestana === "pendiente" && (
            <button
              onClick={() => setSoloAplazadas(!soloAplazadas)}
              className={`flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors ${
                soloAplazadas ? "bg-violet-600 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              <History size={12} strokeWidth={2} />
              Solo aplazadas
            </button>
          )}
          {hayFiltros && (
            <button
              onClick={() => {
                setBusqueda("");
                setFiltroTipo("");
                setSoloAplazadas(false);
                setSoloGrupo(null);
              }}
              className="text-xs font-medium text-slate-500 hover:text-ink"
            >
              Limpiar filtros
            </button>
          )}
          <button
            onClick={() => {
              setModoSeleccion(!modoSeleccion);
              setSeleccionadas(new Set());
            }}
            className={`ml-auto flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
              modoSeleccion ? "bg-accent text-white" : "border border-slate-200 bg-white text-slate-600 hover:border-accent hover:text-accent"
            }`}
          >
            <CheckCheck size={13} strokeWidth={1.75} />
            {modoSeleccion ? "Terminar seleccion" : "Seleccionar varias"}
          </button>
        </div>

        {error && <div className="mt-4 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>}

        <div className="mt-4">
          {cargando ? (
            <div className="surface-card space-y-3 p-5">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="flex animate-pulse items-center gap-3">
                  <div className="h-5 w-5 rounded-full bg-slate-100" />
                  <div className="h-3 flex-1 rounded bg-slate-100" />
                  <div className="h-5 w-20 rounded-full bg-slate-100" />
                </div>
              ))}
            </div>
          ) : filtradas.length === 0 ? (
            <EstadoVacio pestana={pestana} hayFiltros={!!hayFiltros} onNueva={() => setPanel({ modo: "nueva" })} />
          ) : pestana === "pendiente" ? (
            <div className="space-y-4">
              {GRUPOS.filter((g) => porGrupo[g.id].length > 0).map((g) => (
                <GrupoTareas
                  key={g.id}
                  grupo={g}
                  tareas={porGrupo[g.id]}
                  modoSeleccion={modoSeleccion}
                  seleccionadas={seleccionadas}
                  onAlternarSeleccion={alternarSeleccion}
                  onCompletar={(t) => cambiarEstado(t, "completado")}
                  onAplazar={aplazarUnMes}
                  onAbrir={(t) => setPanel({ modo: "editar", tarea: t })}
                />
              ))}
            </div>
          ) : (
            <div className="surface-card divide-y divide-slate-100 overflow-hidden">
              {otrasOrdenadas.map((t) => (
                <FilaTarea
                  key={t.id}
                  tarea={t}
                  modoSeleccion={modoSeleccion}
                  seleccionada={seleccionadas.has(t.id)}
                  onAlternarSeleccion={() => alternarSeleccion(t.id)}
                  onCompletar={() => cambiarEstado(t, t.estado === "completado" ? "pendiente" : "completado")}
                  onAplazar={() => aplazarUnMes(t)}
                  onAbrir={() => setPanel({ modo: "editar", tarea: t })}
                />
              ))}
            </div>
          )}
        </div>
      </main>

      {/* Barra flotante de acciones masivas. */}
      {modoSeleccion && seleccionadas.size > 0 && (
        <div className="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-2xl bg-ink px-5 py-3 text-sm text-white shadow-soft-lg">
          <span className="font-semibold">
            {seleccionadas.size} seleccionada{seleccionadas.size === 1 ? "" : "s"}
          </span>
          <button
            onClick={() => aplicarASeleccionadas({ estado: "completado" }, "completadas")}
            disabled={procesandoMasivo}
            className="flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 font-semibold transition-colors hover:bg-emerald-600 disabled:opacity-50"
          >
            {procesandoMasivo ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} strokeWidth={2} />}
            Completar
          </button>
          <button
            onClick={() => aplicarASeleccionadas({ estado: "no_aplica" }, "marcadas como 'No aplica'")}
            disabled={procesandoMasivo}
            className="rounded-lg px-3 py-1.5 font-medium text-slate-300 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-50"
          >
            No aplica
          </button>
          <button
            onClick={() => setSeleccionadas(new Set())}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-white"
            aria-label="Quitar seleccion"
          >
            <X size={15} />
          </button>
        </div>
      )}

      {/* Aviso inferior (con "Deshacer" cuando aplica). */}
      {aviso && !(modoSeleccion && seleccionadas.size > 0) && (
        <div className="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-4 rounded-xl bg-ink px-4 py-3 text-sm text-white shadow-soft-lg">
          <span>{aviso.texto}</span>
          {aviso.deshacer && (
            <button
              onClick={() => {
                aviso.deshacer();
                setAviso(null);
              }}
              className="font-semibold text-accent-light hover:underline"
            >
              Deshacer
            </button>
          )}
          <button onClick={() => setAviso(null)} className="text-slate-400 hover:text-white" aria-label="Cerrar aviso">
            <X size={14} />
          </button>
        </div>
      )}

      {panel && (
        <PanelTarea
          modo={panel.modo}
          tarea={panel.tarea}
          empresas={empresas}
          onCerrar={() => setPanel(null)}
          onGuardada={(texto) => {
            setPanel(null);
            if (texto) mostrarAviso(texto);
            cargarTareas({ silencioso: true });
            api.obtenerAvanceCumplimiento().then(setAvance).catch(() => {});
          }}
        />
      )}
    </div>
  );
}

function TarjetaIndicador({ titulo, valor, nota, Icono, tono, activa, onClick }) {
  const tonos = {
    rojo: { icono: "bg-red-50 text-red-600", valor: "text-red-600" },
    ambar: { icono: "bg-amber-50 text-amber-600", valor: "text-ink" },
    neutro: { icono: "bg-slate-100 text-slate-500", valor: "text-ink" },
  };
  const t = tonos[tono] || tonos.neutro;
  return (
    <button
      onClick={onClick}
      className={`surface-card p-4 text-left transition-all duration-300 ease-out hover:-translate-y-0.5 ${activa ? "ring-2 ring-accent" : ""}`}
    >
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-slate-500">{titulo}</p>
        <span className={`flex h-7 w-7 items-center justify-center rounded-full ${t.icono}`}>
          <Icono size={14} strokeWidth={2} />
        </span>
      </div>
      <p className={`mt-1 text-2xl font-extrabold ${t.valor}`}>{valor}</p>
      <p className="mt-0.5 text-xs text-slate-500">{nota}</p>
    </button>
  );
}

function GrupoTareas({ grupo, tareas, modoSeleccion, seleccionadas, onAlternarSeleccion, onCompletar, onAplazar, onAbrir }) {
  const [abierto, setAbierto] = useState(true);
  const [verTodas, setVerTodas] = useState(false);
  const visibles = verTodas ? tareas : tareas.slice(0, VISIBLES_POR_GRUPO);
  return (
    <section className="surface-card overflow-hidden">
      <button
        onClick={() => setAbierto(!abierto)}
        className="flex w-full items-center gap-2 border-b border-slate-100 bg-slate-50/60 px-5 py-2.5 text-left"
      >
        {abierto ? <ChevronDown size={14} className="text-slate-400" /> : <ChevronRight size={14} className="text-slate-400" />}
        <span className={`h-2 w-2 rounded-full ${grupo.punto}`} />
        <span className={`text-xs font-bold uppercase tracking-wide ${grupo.texto}`}>{grupo.etiqueta}</span>
        <span className="rounded-full bg-white px-1.5 py-0.5 text-[10px] font-bold text-slate-500 ring-1 ring-slate-200">
          {tareas.length}
        </span>
      </button>
      {abierto && (
        <div className="divide-y divide-slate-100">
          {visibles.map((t) => (
            <FilaTarea
              key={t.id}
              tarea={t}
              modoSeleccion={modoSeleccion}
              seleccionada={seleccionadas.has(t.id)}
              onAlternarSeleccion={() => onAlternarSeleccion(t.id)}
              onCompletar={() => onCompletar(t)}
              onAplazar={() => onAplazar(t)}
              onAbrir={() => onAbrir(t)}
            />
          ))}
          {tareas.length > VISIBLES_POR_GRUPO && (
            <button
              onClick={() => setVerTodas(!verTodas)}
              className="w-full px-5 py-2.5 text-left text-xs font-semibold text-accent hover:bg-slate-50"
            >
              {verTodas ? "Ver menos" : `Ver ${tareas.length - VISIBLES_POR_GRUPO} mas`}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function FilaTarea({ tarea: t, modoSeleccion, seleccionada, onAlternarSeleccion, onCompletar, onAplazar, onAbrir }) {
  const completada = t.estado === "completado";
  const vence = textoVencimiento(t);
  return (
    <div
      className={`group flex items-center gap-3 px-5 py-3 transition-colors duration-200 hover:bg-slate-50 ${
        seleccionada ? "bg-accent-light/40" : ""
      }`}
    >
      {modoSeleccion ? (
        <input
          type="checkbox"
          checked={seleccionada}
          onChange={onAlternarSeleccion}
          className="h-4 w-4 shrink-0 rounded border-slate-300 text-accent focus:ring-accent"
          aria-label="Seleccionar tarea"
        />
      ) : (
        <button
          onClick={onCompletar}
          title={completada ? "Volver a pendiente" : "Marcar como completada"}
          className="shrink-0 rounded-full text-slate-300 transition-colors duration-200 hover:text-emerald-500"
        >
          {completada ? (
            <CheckCircle2 size={20} strokeWidth={1.75} className="text-emerald-500" />
          ) : t.estado === "no_aplica" ? (
            <MinusCircle size={20} strokeWidth={1.75} className="text-slate-400" />
          ) : (
            <Circle size={20} strokeWidth={1.75} />
          )}
        </button>
      )}

      <button onClick={onAbrir} className="min-w-0 flex-1 text-left">
        <div className="flex items-center gap-2">
          <span className={`truncate text-sm ${completada ? "text-slate-400 line-through" : "font-medium text-ink"}`}>
            {t.titulo}
          </span>
          {(t.prioridad === "alta" || t.prioridad === "urgente") && !completada && (
            <Flag size={13} strokeWidth={2} className={`shrink-0 ${COLOR_PRIORIDAD[t.prioridad]}`} aria-label={`Prioridad ${t.prioridad}`} />
          )}
          {t.aplazada && (
            <span title={`Vencimiento original: ${formatoFecha(t.fecha_vencimiento_original)}`}>
              <History size={13} strokeWidth={2} className="shrink-0 text-violet-500" />
            </span>
          )}
        </div>
        <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-slate-500">
          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${PUNTO_TIPO[t.tipo] || PUNTO_TIPO.otro}`} />
          <span className="shrink-0">{ETIQUETAS_TIPO[t.tipo] || t.tipo}</span>
          <span className="text-slate-300">·</span>
          <Building2 size={11} strokeWidth={1.75} className="shrink-0" />
          <span className="truncate">{t.empresa_razon_social}</span>
          {t.periodo && (
            <>
              <span className="text-slate-300">·</span>
              <span className="shrink-0">Periodo {t.periodo}</span>
            </>
          )}
        </div>
      </button>

      {t.estado === "pendiente" && !modoSeleccion && (
        <button
          onClick={onAplazar}
          title="Aplazar 1 mes"
          className="hidden shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-slate-500 hover:bg-white hover:text-accent group-hover:flex"
        >
          <CalendarClock size={13} strokeWidth={1.75} />
          +1 mes
        </button>
      )}
      <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${vence.clase}`} title={formatoFecha(t.fecha_vencimiento) || undefined}>
        {vence.texto === "Sin fecha" ? (
          <span className="flex items-center gap-1">
            <Clock size={11} strokeWidth={2} />
            Sin fecha
          </span>
        ) : (
          vence.texto
        )}
      </span>
    </div>
  );
}

function EstadoVacio({ pestana, hayFiltros, onNueva }) {
  if (hayFiltros) {
    return (
      <div className="surface-card p-10 text-center">
        <Search size={26} strokeWidth={1.5} className="mx-auto text-slate-300" />
        <p className="mt-3 text-sm text-slate-500">Ninguna tarea coincide con los filtros.</p>
      </div>
    );
  }
  if (pestana === "pendiente") {
    return (
      <div className="surface-card p-10 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-50">
          <CheckCircle2 size={24} strokeWidth={1.75} className="text-emerald-500" />
        </div>
        <p className="mt-3 text-base font-bold text-ink">Todo al dia</p>
        <p className="mt-1 text-sm text-slate-500">No tienes tareas pendientes. Las del mes se crean solas a partir de las obligaciones de cada empresa.</p>
        <button onClick={onNueva} className="mt-4 text-sm font-semibold text-accent hover:underline">
          Crear una tarea
        </button>
      </div>
    );
  }
  return (
    <div className="surface-card p-10 text-center">
      <ListChecks size={26} strokeWidth={1.5} className="mx-auto text-slate-300" />
      <p className="mt-3 text-sm text-slate-500">No hay tareas en esta pestana.</p>
    </div>
  );
}

// Panel lateral (en vez de una ventana al centro) para crear o editar: la
// lista sigue a la vista y se cierra con Esc o tocando afuera.
function PanelTarea({ modo, tarea, empresas, onCerrar, onGuardada }) {
  const esNueva = modo === "nueva";
  const [empresaId, setEmpresaId] = useState("");
  const [titulo, setTitulo] = useState("");
  const [tipo, setTipo] = useState("otro");
  const [estado, setEstado] = useState(tarea?.estado || "pendiente");
  const [prioridad, setPrioridad] = useState(tarea?.prioridad || "media");
  const [fecha, setFecha] = useState(tarea?.fecha_vencimiento ? tarea.fecha_vencimiento.slice(0, 10) : "");
  const [observaciones, setObservaciones] = useState(tarea?.observaciones || "");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const [confirmarEliminar, setConfirmarEliminar] = useState(false);

  useEffect(() => {
    function alTeclear(e) {
      if (e.key === "Escape") onCerrar();
    }
    window.addEventListener("keydown", alTeclear);
    return () => window.removeEventListener("keydown", alTeclear);
  }, [onCerrar]);

  async function guardar(e) {
    e.preventDefault();
    setError("");
    if (esNueva && !empresaId) {
      setError("Elige la empresa.");
      return;
    }
    setGuardando(true);
    try {
      const fechaIso = fecha ? new Date(fecha).toISOString() : null;
      if (esNueva) {
        await api.crearTareaManual({
          empresa_id: empresaId,
          titulo,
          tipo,
          prioridad,
          fecha_vencimiento: fechaIso,
          observaciones: observaciones || null,
        });
        onGuardada("Tarea creada.");
      } else {
        await api.actualizarTarea(tarea.id, {
          estado,
          prioridad,
          fecha_vencimiento: fechaIso,
          observaciones: observaciones || null,
        });
        onGuardada("Cambios guardados.");
      }
    } catch (err) {
      setError(err.message);
      setGuardando(false);
    }
  }

  async function eliminar() {
    setConfirmarEliminar(false);
    setGuardando(true);
    try {
      await api.eliminarTarea(tarea.id);
      onGuardada("Tarea eliminada.");
    } catch (err) {
      setError(err.message);
      setGuardando(false);
    }
  }

  const etiqueta = "mb-1.5 block text-xs font-semibold text-slate-500";

  return (
    <>
      <div className="fixed inset-0 z-50 flex justify-end bg-ink/40" onClick={onCerrar}>
        <form
          onSubmit={guardar}
          onClick={(e) => e.stopPropagation()}
          className="flex h-full w-full max-w-md flex-col bg-white shadow-soft-lg animate-fade-in-up"
        >
          <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-6 py-5">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{esNueva ? "Nueva tarea" : "Editar tarea"}</p>
              {!esNueva && (
                <>
                  <h2 className="mt-1 text-lg font-bold leading-snug text-ink">{tarea.titulo}</h2>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                    <span className={`h-1.5 w-1.5 rounded-full ${PUNTO_TIPO[tarea.tipo] || PUNTO_TIPO.otro}`} />
                    {ETIQUETAS_TIPO[tarea.tipo] || tarea.tipo}
                    {tarea.periodo && <span>· Periodo {tarea.periodo}</span>}
                  </div>
                  <Link href={`/empresas/${tarea.empresa_id}`} className="mt-2 flex items-center gap-1.5 text-xs font-medium text-accent hover:underline">
                    <Building2 size={12} strokeWidth={1.75} />
                    {tarea.empresa_razon_social} · {tarea.empresa_ruc}
                  </Link>
                </>
              )}
            </div>
            <button type="button" onClick={onCerrar} className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-ink" aria-label="Cerrar">
              <X size={18} strokeWidth={1.75} />
            </button>
          </div>

          <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
            {error && <div className="rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>}

            {esNueva && (
              <>
                <div>
                  <label className={etiqueta}>Empresa</label>
                  <select value={empresaId} onChange={(e) => setEmpresaId(e.target.value)} required className="campo-input">
                    <option value="">Elige una empresa...</option>
                    {empresas.map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.razon_social} -- {e.ruc}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={etiqueta}>Que hay que hacer</label>
                  <input
                    value={titulo}
                    onChange={(e) => setTitulo(e.target.value)}
                    required
                    autoFocus
                    placeholder="Ej.: Responder esquela de SUNAT"
                    className="campo-input"
                  />
                </div>
                <div>
                  <label className={etiqueta}>Tipo</label>
                  <select value={tipo} onChange={(e) => setTipo(e.target.value)} className="campo-input">
                    {Object.entries(ETIQUETAS_TIPO).map(([valor, texto]) => (
                      <option key={valor} value={valor}>
                        {texto}
                      </option>
                    ))}
                  </select>
                </div>
              </>
            )}

            {!esNueva && (
              <div>
                <label className={etiqueta}>Estado</label>
                <div className="grid grid-cols-3 gap-1.5 rounded-xl bg-slate-100 p-1">
                  {[
                    { valor: "pendiente", texto: "Pendiente", Icono: Circle },
                    { valor: "completado", texto: "Completada", Icono: CheckCircle2 },
                    { valor: "no_aplica", texto: "No aplica", Icono: MinusCircle },
                  ].map(({ valor, texto, Icono }) => (
                    <button
                      type="button"
                      key={valor}
                      onClick={() => setEstado(valor)}
                      className={`flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-semibold transition-all duration-200 ${
                        estado === valor ? "bg-white text-ink shadow-soft" : "text-slate-500 hover:text-ink"
                      }`}
                    >
                      <Icono size={13} strokeWidth={2} className={estado === valor && valor === "completado" ? "text-emerald-500" : ""} />
                      {texto}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div>
              <label className={etiqueta}>Prioridad</label>
              <div className="grid grid-cols-4 gap-1.5">
                {PRIORIDADES.map((p) => (
                  <button
                    type="button"
                    key={p.valor}
                    onClick={() => setPrioridad(p.valor)}
                    className={`flex items-center justify-center gap-1 rounded-lg border px-2 py-2 text-xs font-semibold transition-all duration-200 ${
                      prioridad === p.valor ? "border-accent bg-accent-light/60 text-ink" : "border-slate-200 text-slate-500 hover:border-slate-300"
                    }`}
                  >
                    <Flag size={12} strokeWidth={2} className={p.color} />
                    {p.etiqueta}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className={etiqueta}>Fecha limite {esNueva && "(opcional)"}</label>
              <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} className="campo-input" />
              <div className="mt-2 flex flex-wrap gap-1.5">
                {[
                  { texto: "Hoy", valor: () => sumarDias(null, 0) },
                  { texto: "+1 semana", valor: () => sumarDias(fecha || null, 7) },
                  { texto: "+1 mes", valor: () => sumarMeses(fecha || null, 1) },
                ].map((atajo) => (
                  <button
                    type="button"
                    key={atajo.texto}
                    onClick={() => setFecha(atajo.valor())}
                    className="rounded-full border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 hover:border-accent hover:text-accent"
                  >
                    {atajo.texto}
                  </button>
                ))}
                {fecha && (
                  <button type="button" onClick={() => setFecha("")} className="px-1.5 py-1 text-xs text-slate-400 hover:text-ink">
                    Quitar fecha
                  </button>
                )}
              </div>
              {!esNueva && tarea.aplazada && (
                <p className="mt-2 flex items-center gap-1 text-xs text-violet-600">
                  <History size={12} strokeWidth={2} />
                  Vencia originalmente el {formatoFecha(tarea.fecha_vencimiento_original)}
                </p>
              )}
            </div>

            <div>
              <label className={etiqueta}>Notas</label>
              <textarea
                value={observaciones}
                onChange={(e) => setObservaciones(e.target.value)}
                rows={4}
                placeholder="Detalles, acuerdos con el cliente, numero de expediente..."
                className="campo-input"
              />
            </div>
          </div>

          <div className="flex items-center justify-between gap-2 border-t border-slate-100 px-6 py-4">
            {!esNueva ? (
              <button
                type="button"
                onClick={() => setConfirmarEliminar(true)}
                disabled={guardando}
                className="flex items-center gap-1 text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
              >
                <Trash2 size={13} strokeWidth={1.75} />
                Eliminar
              </button>
            ) : (
              <span />
            )}
            <div className="flex items-center gap-2">
              <button type="button" onClick={onCerrar} className="rounded-lg px-4 py-2 text-sm font-medium text-slate-500 hover:bg-slate-50">
                Cancelar
              </button>
              <button
                type="submit"
                disabled={guardando}
                className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
              >
                {guardando && <Loader2 size={14} strokeWidth={2} className="animate-spin" />}
                {esNueva ? "Crear tarea" : "Guardar"}
              </button>
            </div>
          </div>
        </form>
      </div>

      {confirmarEliminar && (
        <ConfirmDialog
          titulo="Eliminar esta tarea?"
          textoConfirmar="Si, eliminar"
          peligroso
          onConfirmar={eliminar}
          onCancelar={() => setConfirmarEliminar(false)}
        />
      )}
    </>
  );
}
