"use client";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  ListChecks,
  Plus,
  X,
  Loader2,
  RefreshCw,
  Building2,
  CheckCircle2,
  Circle,
  MinusCircle,
  Clock,
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

const COLOR_TIPO = {
  igv_renta: "bg-emerald-50 text-emerald-700",
  planilla: "bg-accent-light text-accent",
  afp: "bg-violet-50 text-violet-700",
  sbs: "bg-amber-50 text-amber-700",
  cts: "bg-sky-50 text-sky-700",
  itan: "bg-rose-50 text-rose-700",
  sire: "bg-cyan-50 text-cyan-700",
  otro: "bg-slate-100 text-slate-600",
};

const COLOR_PRIORIDAD = {
  baja: "bg-slate-100 text-slate-600",
  media: "bg-blue-50 text-blue-700",
  alta: "bg-amber-100 text-amber-800",
  urgente: "bg-red-100 text-red-700",
};

const ETIQUETAS_FILTRO = [
  { valor: "pendiente", etiqueta: "Pendientes" },
  { valor: "vencida", etiqueta: "Vencidas" },
  { valor: "completado", etiqueta: "Completadas" },
  { valor: "no_aplica", etiqueta: "No aplica" },
  { valor: "", etiqueta: "Todas" },
];

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
  const [tareas, setTareas] = useState([]);
  const [empresas, setEmpresas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  // El Dashboard enlaza aca con ?estado=vencida para llegar directo con el
  // filtro activado (ver TarjetaMetricaColor "Tareas vencidas").
  const [filtroEstado, setFiltroEstado] = useState(searchParams.get("estado") || "pendiente");
  // Cartera: "" = todas, "yo" = solo las de mi cartera, o el id de otro
  // usuario del tenant (para que un socio/admin vea la cartera de alguien
  // mas puntual).
  const [filtroAsignado, setFiltroAsignado] = useState("");
  const [usuarios, setUsuarios] = useState([]);
  const [miUsuarioId, setMiUsuarioId] = useState(null);
  const [generando, setGenerando] = useState(false);
  const [mostrarNueva, setMostrarNueva] = useState(false);
  const [tareaSeleccionada, setTareaSeleccionada] = useState(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    cargarEmpresas();
    api.me().then((yo) => setMiUsuarioId(yo.id)).catch(() => {});
    api.listarUsuarios().then(setUsuarios).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    cargarTareas();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtroEstado, filtroAsignado, miUsuarioId]);

  async function cargarEmpresas() {
    try {
      const data = await api.listarEmpresas();
      setEmpresas(data);
    } catch (err) {
      // silencioso -- solo hace falta para el selector de "Nueva tarea"
    }
  }

  async function cargarTareas() {
    setCargando(true);
    setError("");
    try {
      const filtros = {};
      if (filtroEstado) filtros.estado = filtroEstado;
      if (filtroAsignado === "yo" && miUsuarioId) filtros.asignadoAUsuarioId = miUsuarioId;
      else if (filtroAsignado && filtroAsignado !== "yo") filtros.asignadoAUsuarioId = filtroAsignado;
      const data = await api.listarTareas(filtros);
      setTareas(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setCargando(false);
    }
  }

  async function generarDelMes() {
    setGenerando(true);
    try {
      const hoy = new Date();
      const resultado = await api.generarTareas(hoy.getFullYear(), hoy.getMonth() + 1);
      alert(
        resultado.tareas_creadas === 0
          ? "No hay tareas nuevas para generar este mes (ya estaban creadas, o no hay obligaciones configuradas)."
          : `Se generaron ${resultado.tareas_creadas} tarea(s) nueva(s) para el periodo ${resultado.periodo}.`
      );
      await cargarTareas();
    } catch (err) {
      alert(err.message);
    } finally {
      setGenerando(false);
    }
  }

  async function cambiarEstado(tarea, nuevoEstado) {
    try {
      await api.actualizarTarea(tarea.id, { estado: nuevoEstado });
      await cargarTareas();
    } catch (err) {
      alert(err.message);
    }
  }

  const tareasOrdenadas = useMemo(() => {
    return [...tareas].sort((a, b) => {
      if (!a.fecha_vencimiento && !b.fecha_vencimiento) return 0;
      if (!a.fecha_vencimiento) return 1;
      if (!b.fecha_vencimiento) return -1;
      return new Date(a.fecha_vencimiento) - new Date(b.fecha_vencimiento);
    });
  }, [tareas]);

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 pb-8 pt-24 xl:px-12">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-ink">Tareas</h1>
            <p className="mt-1 text-sm text-slate-600">
              Agenda de obligaciones por empresa -- Planilla, AFP, SBS y pendientes sueltos
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={generarDelMes}
              disabled={generando}
              title="Genera las tareas del mes actual para todas las obligaciones activas configuradas"
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition-all duration-300 ease-out hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {generando ? <Loader2 size={15} strokeWidth={1.5} className="animate-spin" /> : <RefreshCw size={15} strokeWidth={1.5} />}
              Generar tareas del mes
            </button>
            <button
              onClick={() => setMostrarNueva(true)}
              className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark"
            >
              <Plus size={15} strokeWidth={1.5} />
              Nueva tarea
            </button>
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-1.5">
            {ETIQUETAS_FILTRO.map(({ valor, etiqueta }) => (
              <button
                key={valor || "todas"}
                onClick={() => setFiltroEstado(valor)}
                className={`rounded-full px-3.5 py-1.5 text-xs font-semibold transition-colors duration-300 ease-out ${
                  filtroEstado === valor ? "bg-accent text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {etiqueta}
              </button>
            ))}
          </div>
          <select
            value={filtroAsignado}
            onChange={(e) => setFiltroAsignado(e.target.value)}
            title="Cartera: filtrar por quien tiene asignada la empresa de cada tarea"
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 outline-none"
          >
            <option value="">Todas las carteras</option>
            <option value="yo">Mi cartera</option>
            {usuarios.filter((u) => u.id !== miUsuarioId).map((u) => (
              <option key={u.id} value={u.id}>
                {u.email}
              </option>
            ))}
          </select>
        </div>

        {error && (
          <div className="mt-6 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
        )}

        {cargando ? (
          <p className="mt-8 text-sm text-slate-500">Cargando...</p>
        ) : tareasOrdenadas.length === 0 ? (
          <div className="surface-card mt-6 p-10 text-center">
            <ListChecks size={28} strokeWidth={1.2} className="mx-auto text-slate-300" />
            <p className="mt-3 text-sm text-slate-500">
              No hay tareas en este filtro. Configura obligaciones desde el detalle de cada empresa, o presiona
              &quot;Generar tareas del mes&quot; si ya tenes alguna configurada.
            </p>
          </div>
        ) : (
          <div className="surface-card mt-6 divide-y divide-slate-100 overflow-hidden">
            {tareasOrdenadas.map((t) => {
              const dias = diasRestantes(t.fecha_vencimiento);
              return (
                <div key={t.id} className="flex items-center gap-3 px-5 py-4 transition-colors duration-300 ease-out hover:bg-slate-50">
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      onClick={() => cambiarEstado(t, t.estado === "completado" ? "pendiente" : "completado")}
                      title={t.estado === "completado" ? "Marcar pendiente" : "Marcar completada"}
                      className="flex items-center justify-center rounded-lg p-1.5 text-slate-400 transition-colors duration-300 ease-out hover:bg-slate-100 hover:text-emerald-600"
                    >
                      {t.estado === "completado" ? (
                        <CheckCircle2 size={20} strokeWidth={1.5} className="text-emerald-500" />
                      ) : (
                        <Circle size={20} strokeWidth={1.5} />
                      )}
                    </button>
                  </div>

                  <button onClick={() => setTareaSeleccionada(t)} className="min-w-0 flex-1 text-left">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className={`text-sm ${t.estado === "completado" ? "text-slate-400 line-through" : "font-medium text-ink"}`}>
                        {t.titulo}
                      </span>
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${COLOR_TIPO[t.tipo] || COLOR_TIPO.otro}`}>
                        {ETIQUETAS_TIPO[t.tipo] || t.tipo}
                      </span>
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${COLOR_PRIORIDAD[t.prioridad] || COLOR_PRIORIDAD.media}`}>
                        {t.prioridad}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-500">
                      <Building2 size={12} strokeWidth={1.5} className="shrink-0" />
                      <span className="truncate">{t.empresa_razon_social}</span>
                      <span className="text-slate-300">&middot;</span>
                      <span>{t.empresa_ruc}</span>
                    </div>
                  </button>

                  <div className="shrink-0 text-right">
                    {t.fecha_vencimiento ? (
                      <>
                        <div className="text-sm font-semibold text-ink">{formatoFecha(t.fecha_vencimiento)}</div>
                        {t.estado === "pendiente" && dias != null && (
                          <div className={`text-xs ${dias < 0 ? "text-red-600" : dias <= 3 ? "text-amber-600" : "text-slate-400"}`}>
                            {dias < 0 ? `vencio hace ${Math.abs(dias)}d` : dias === 0 ? "vence hoy" : `en ${dias}d`}
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="flex items-center gap-1 text-xs font-medium text-amber-600">
                        <Clock size={12} strokeWidth={1.5} />
                        Sin fecha
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>

      {mostrarNueva && (
        <ModalNuevaTarea
          empresas={empresas}
          onClose={() => setMostrarNueva(false)}
          onCreada={() => {
            setMostrarNueva(false);
            cargarTareas();
          }}
        />
      )}

      {tareaSeleccionada && (
        <ModalEditarTarea
          tarea={tareaSeleccionada}
          onClose={() => setTareaSeleccionada(null)}
          onGuardada={() => {
            setTareaSeleccionada(null);
            cargarTareas();
          }}
        />
      )}
    </div>
  );
}

function ModalNuevaTarea({ empresas, onClose, onCreada }) {
  const [empresaId, setEmpresaId] = useState(empresas[0]?.id || "");
  const [titulo, setTitulo] = useState("");
  const [tipo, setTipo] = useState("otro");
  const [prioridad, setPrioridad] = useState("media");
  const [fechaVencimiento, setFechaVencimiento] = useState("");
  const [observaciones, setObservaciones] = useState("");
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    if (!empresaId) {
      setError("Selecciona una empresa.");
      return;
    }
    setError("");
    setGuardando(true);
    try {
      await api.crearTareaManual({
        empresa_id: empresaId,
        titulo,
        tipo,
        prioridad,
        fecha_vencimiento: fechaVencimiento ? new Date(fechaVencimiento).toISOString() : null,
        observaciones: observaciones || null,
      });
      onCreada();
    } catch (err) {
      setError(err.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-6" onClick={onClose}>
      <form
        onSubmit={onSubmit}
        className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-soft-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-ink">Nueva tarea</h2>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-ink">
            <X size={18} strokeWidth={1.5} />
          </button>
        </div>

        {error && (
          <div className="mt-4 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
        )}

        <div className="mt-4 space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Empresa</label>
            <select value={empresaId} onChange={(e) => setEmpresaId(e.target.value)} required className="campo-input">
              <option value="">Selecciona...</option>
              {empresas.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.razon_social} -- {e.ruc}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Titulo</label>
            <input value={titulo} onChange={(e) => setTitulo(e.target.value)} required placeholder="Responder esquela de SUNAT" className="campo-input" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Tipo</label>
              <select value={tipo} onChange={(e) => setTipo(e.target.value)} className="campo-input">
                {Object.entries(ETIQUETAS_TIPO).map(([valor, etiqueta]) => (
                  <option key={valor} value={valor}>{etiqueta}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Prioridad</label>
              <select value={prioridad} onChange={(e) => setPrioridad(e.target.value)} className="campo-input">
                <option value="baja">Baja</option>
                <option value="media">Media</option>
                <option value="alta">Alta</option>
                <option value="urgente">Urgente</option>
              </select>
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Fecha limite (opcional)</label>
            <input type="date" value={fechaVencimiento} onChange={(e) => setFechaVencimiento(e.target.value)} className="campo-input" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Observaciones</label>
            <textarea value={observaciones} onChange={(e) => setObservaciones(e.target.value)} rows={2} className="campo-input" />
          </div>
        </div>

        <button
          type="submit"
          disabled={guardando}
          className="mt-5 flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
        >
          {guardando && <Loader2 size={14} strokeWidth={1.5} className="animate-spin" />}
          {guardando ? "Guardando..." : "Crear tarea"}
        </button>
      </form>
    </div>
  );
}

function ModalEditarTarea({ tarea, onClose, onGuardada }) {
  const [estado, setEstado] = useState(tarea.estado);
  const [prioridad, setPrioridad] = useState(tarea.prioridad);
  const [fechaVencimiento, setFechaVencimiento] = useState(
    tarea.fecha_vencimiento ? tarea.fecha_vencimiento.slice(0, 10) : ""
  );
  const [observaciones, setObservaciones] = useState(tarea.observaciones || "");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const [mostrarConfirmarEliminar, setMostrarConfirmarEliminar] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setGuardando(true);
    try {
      await api.actualizarTarea(tarea.id, {
        estado,
        prioridad,
        fecha_vencimiento: fechaVencimiento ? new Date(fechaVencimiento).toISOString() : null,
        observaciones: observaciones || null,
      });
      onGuardada();
    } catch (err) {
      setError(err.message);
    } finally {
      setGuardando(false);
    }
  }

  async function eliminar() {
    setMostrarConfirmarEliminar(false);
    setGuardando(true);
    try {
      await api.eliminarTarea(tarea.id);
      onGuardada();
    } catch (err) {
      setError(err.message);
      setGuardando(false);
    }
  }

  return (
    <>
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-6" onClick={onClose}>
      <form
        onSubmit={onSubmit}
        className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-soft-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-ink">{tarea.titulo}</h2>
            <p className="mt-0.5 truncate text-xs text-slate-500">
              {tarea.empresa_razon_social} &middot; {tarea.empresa_ruc}
            </p>
          </div>
          <button type="button" onClick={onClose} className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-ink">
            <X size={18} strokeWidth={1.5} />
          </button>
        </div>

        {error && (
          <div className="mt-4 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
        )}

        <div className="mt-4 space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Estado</label>
            <div className="flex gap-1.5">
              {[
                { valor: "pendiente", etiqueta: "Pendiente", Icon: Circle },
                { valor: "completado", etiqueta: "Completado", Icon: CheckCircle2 },
                { valor: "no_aplica", etiqueta: "No aplica", Icon: MinusCircle },
              ].map(({ valor, etiqueta, Icon }) => (
                <button
                  type="button"
                  key={valor}
                  onClick={() => setEstado(valor)}
                  className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg border px-2 py-2 text-xs font-medium transition-all duration-300 ease-out ${
                    estado === valor ? "border-accent bg-accent-light text-accent" : "border-slate-200 text-slate-500 hover:border-accent hover:text-accent"
                  }`}
                >
                  <Icon size={14} strokeWidth={1.5} />
                  {etiqueta}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Prioridad</label>
              <select value={prioridad} onChange={(e) => setPrioridad(e.target.value)} className="campo-input">
                <option value="baja">Baja</option>
                <option value="media">Media</option>
                <option value="alta">Alta</option>
                <option value="urgente">Urgente</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Fecha limite</label>
              <input type="date" value={fechaVencimiento} onChange={(e) => setFechaVencimiento(e.target.value)} className="campo-input" />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Observaciones</label>
            <textarea value={observaciones} onChange={(e) => setObservaciones(e.target.value)} rows={3} className="campo-input" />
          </div>
        </div>

        <div className="mt-5 flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => setMostrarConfirmarEliminar(true)}
            disabled={guardando}
            className="text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
          >
            Eliminar tarea
          </button>
          <button
            type="submit"
            disabled={guardando}
            className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
          >
            {guardando && <Loader2 size={14} strokeWidth={1.5} className="animate-spin" />}
            {guardando ? "Guardando..." : "Guardar"}
          </button>
        </div>
      </form>
    </div>

    {mostrarConfirmarEliminar && (
      <ConfirmDialog
        titulo="Eliminar esta tarea?"
        textoConfirmar="Si, eliminar"
        peligroso
        onConfirmar={eliminar}
        onCancelar={() => setMostrarConfirmarEliminar(false)}
      />
    )}
    </>
  );
}
