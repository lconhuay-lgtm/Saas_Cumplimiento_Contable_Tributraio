"use client";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Inbox,
  Activity,
  CheckCircle2,
  XCircle,
  ArrowRight,
  AlertTriangle,
  CalendarClock,
  Bell,
  Clock,
  ListChecks,
  RefreshCw,
} from "lucide-react";
import Sidebar from "../../components/Sidebar";
import { api, getToken } from "../../lib/api";

function formatoRelativoCorto(fechaIso) {
  if (!fechaIso) return "--";
  const diffMs = Date.now() - new Date(fechaIso).getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "ahora";
  if (diffMin < 60) return `${diffMin}m`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h`;
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d`;
}

export default function DashboardPage() {
  const router = useRouter();
  const [resumen, setResumen] = useState(null);
  const [tareasPendientes, setTareasPendientes] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function cargar() {
    setCargando(true);
    setError("");
    try {
      const [datosResumen, datosTareas] = await Promise.all([
        api.dashboardResumen(),
        api.listarTareas({ estado: "pendiente" }).catch(() => []),
      ]);
      setResumen(datosResumen);
      setTareasPendientes(datosTareas);
    } catch (err) {
      setError(err.message);
    } finally {
      setCargando(false);
    }
  }

  const ultimaSincronizacion = resumen?.actividad_reciente?.[0];

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 py-8 xl:px-12">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-ink">Dashboard</h1>
          <p className="mt-1 text-sm text-slate-600">
            {resumen ? `${resumen.empresas_activas} de ${resumen.empresas_totales} empresas activas` : "Resumen general de todas tus empresas monitoreadas"}
          </p>
        </div>

        {error && (
          <div className="mt-6 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
        )}

        {cargando || !resumen ? (
          <p className="mt-8 text-sm text-slate-500">Cargando...</p>
        ) : (
          <>
            {/* Fila de metricas estilo "panel de control": tarjetas a color
                solido con icono en circulo translucido -- lectura
                instantanea de que necesita atencion, inspirado en el
                dashboard de BuzOne. */}
            <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <TarjetaMetricaColor
                Icon={Bell}
                color="emerald"
                label="Notificaciones nuevas"
                value={resumen.pendientes_totales}
                detalle="SUNAT + SUNAFIL"
                href="/empresas?hoy=1"
              />
              <TarjetaMetricaColor
                Icon={Clock}
                color="amber"
                label="Eventos"
                value={resumen.proximos_vencimientos?.length || 0}
                detalle="Vencen pronto"
                href="/cronograma"
              />
              <TarjetaMetricaColor
                Icon={ListChecks}
                color="rose"
                label="Tareas"
                value={tareasPendientes?.length ?? 0}
                detalle="Pendientes"
                href="/tareas"
              />
              <TarjetaMetricaColor
                Icon={RefreshCw}
                color="teal"
                label="Ultima sincronizacion"
                value={formatoRelativoCorto(ultimaSincronizacion?.finalizado_en)}
                detalle={
                  !ultimaSincronizacion
                    ? "Sin consultas todavia"
                    : ultimaSincronizacion.estado === "error"
                    ? "con errores"
                    : "exitosa"
                }
              />
            </div>

            <SeccionAvanceCumplimiento />

            {resumen.cambios_estado_contribuyente_recientes.length > 0 && (
              <SeccionCambiosEstadoContribuyente cambios={resumen.cambios_estado_contribuyente_recientes} />
            )}

            {resumen.cambios_domicilio_recientes.length > 0 && (
              <SeccionCambiosDomicilio cambios={resumen.cambios_domicilio_recientes} />
            )}

            {resumen.proximos_vencimientos?.length > 0 && (
              <SeccionProximosVencimientos vencimientos={resumen.proximos_vencimientos} />
            )}

            <div className="mt-10 grid grid-cols-1 gap-8 xl:grid-cols-2">
              <SeccionEmpresasConPendientes empresas={resumen.empresas_con_pendientes} />
              <SeccionActividadReciente actividad={resumen.actividad_reciente} />
            </div>
          </>
        )}
      </main>
    </div>
  );
}

// Paleta solida por color -- fondo a color completo (no solo un chip de
// icono), como las tarjetas del competidor. Cada tarjeta lleva su propio
// icono en un circulo translucido arriba a la izquierda.
const COLORES_METRICA = {
  emerald: "bg-emerald-500",
  amber: "bg-amber-500",
  rose: "bg-rose-500",
  teal: "bg-teal-600",
};

function TarjetaMetricaColor({ Icon, color, label, value, detalle, href }) {
  const Wrapper = href ? Link : "div";
  return (
    <Wrapper
      href={href}
      className={`animate-fade-in-up flex items-start gap-3.5 rounded-2xl p-5 text-white shadow-soft transition-all duration-300 ease-out ${COLORES_METRICA[color]} ${
        href ? "hover:-translate-y-0.5 hover:shadow-soft-lg" : ""
      }`}
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/20">
        <Icon size={18} strokeWidth={1.75} />
      </div>
      <div className="min-w-0">
        <div className="text-3xl font-extrabold leading-tight tracking-tight">{value}</div>
        <div className="mt-0.5 text-xs font-semibold uppercase tracking-wide text-white/90">{label}</div>
        <div className="mt-0.5 truncate text-xs text-white/70">{detalle}</div>
      </div>
    </Wrapper>
  );
}

// Modulo de Tareas/Agenda: panel "Avance de Cumplimiento" -- por cada tipo
// de obligacion configurada (Planilla/AFP/Reporte SBS/Otro), cuantas
// tareas hay este periodo y cuantas ya se completaron, con un selector de
// periodo tributario igual en espiritu al del competidor.
function SeccionAvanceCumplimiento() {
  const [periodo, setPeriodo] = useState(() => {
    const hoy = new Date();
    return `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, "0")}`;
  });
  const [avance, setAvance] = useState(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [periodo]);

  async function cargar() {
    setCargando(true);
    try {
      const data = await api.obtenerAvanceCumplimiento(periodo);
      setAvance(data);
    } catch (err) {
      // silencioso -- no es critico para el resto del dashboard
    } finally {
      setCargando(false);
    }
  }

  const opcionesPeriodo = useMemo(() => {
    const opciones = [];
    const base = new Date();
    for (let i = 0; i < 12; i++) {
      const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
      const valor = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      const etiqueta = d.toLocaleDateString("es-PE", { month: "long", year: "numeric" });
      opciones.push({ valor, etiqueta: etiqueta.charAt(0).toUpperCase() + etiqueta.slice(1) });
    }
    return opciones;
  }, []);

  return (
    <section className="mt-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">Avance de cumplimiento</h2>
          <p className="mt-0.5 text-xs text-slate-400">
            Segun las obligaciones (Planilla/AFP/SBS) que configuraste por empresa -- ver detalle de empresa.
          </p>
        </div>
        <select
          value={periodo}
          onChange={(e) => setPeriodo(e.target.value)}
          className="campo-input w-auto text-xs"
        >
          {opcionesPeriodo.map((o) => (
            <option key={o.valor} value={o.valor}>
              {o.etiqueta}
            </option>
          ))}
        </select>
      </div>

      {cargando ? (
        <p className="mt-3 text-sm text-slate-500">Cargando...</p>
      ) : !avance || avance.total.total === 0 ? (
        <div className="surface-card mt-3 p-6 text-center text-sm text-slate-500">
          Sin tareas para este periodo. Configura obligaciones (Planilla, AFP, Reporte SBS) desde el detalle de
          cada empresa, y presiona &quot;Generar tareas del mes&quot; en la pagina Tareas.
        </div>
      ) : (
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {avance.por_tipo.map((p) => (
            <TarjetaAvance key={p.tipo} item={p} />
          ))}
          <TarjetaAvance item={avance.total} destacada />
        </div>
      )}
    </section>
  );
}

function TarjetaAvance({ item, destacada }) {
  return (
    <div className="surface-card overflow-hidden">
      <div className={`px-4 py-2.5 text-sm font-bold text-white ${destacada ? "bg-teal-600" : "bg-ink"}`}>
        {item.tipo}
      </div>
      <div className="grid grid-cols-2 gap-2 p-4">
        <div>
          <div className="text-2xl font-extrabold text-ink">{item.total}</div>
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Total</div>
        </div>
        <div>
          <div className="text-2xl font-extrabold text-emerald-600">{item.completados}</div>
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Completados</div>
        </div>
      </div>
      <div className="px-4 pb-4">
        <div className="flex items-center justify-between text-xs font-semibold text-slate-500">
          <span>Avance</span>
          <span>{item.avance}%</span>
        </div>
        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-emerald-500 transition-all duration-500"
            style={{ width: `${item.avance}%` }}
          />
        </div>
      </div>
    </div>
  );
}

function SeccionCambiosEstadoContribuyente({ cambios }) {
  return (
    <section className="mt-6 max-w-5xl rounded-2xl border border-red-200 bg-red-50 p-5 animate-fade-in-up">
      <div className="flex items-center gap-2 text-red-700">
        <AlertTriangle size={17} strokeWidth={1.5} />
        <h2 className="text-sm font-bold uppercase tracking-wide">Cambios de estado del contribuyente</h2>
      </div>
      <p className="mt-1 text-xs text-red-600/80">
        Puede afectar la declaracion de impuestos -- revisa estas empresas.
      </p>
      <div className="mt-3 divide-y divide-red-100">
        {cambios.map((c) => (
          <Link
            key={c.empresa_id}
            href={`/empresas/${c.empresa_id}`}
            className="-mx-2 flex items-center justify-between gap-3 rounded-lg px-2 py-3 transition-colors duration-300 ease-out hover:bg-white/70"
          >
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-ink">{c.empresa_razon_social}</div>
              <div className="text-xs text-slate-500">
                {c.empresa_ruc} &middot; {new Date(c.actualizada_en).toLocaleDateString()}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <span className="text-xs font-medium text-slate-400">{c.estado_anterior || "?"}</span>
              <ArrowRight size={12} strokeWidth={1.5} className="text-slate-400" />
              <span
                className={`rounded-md px-2 py-0.5 text-[11px] font-bold ${
                  c.estado_actual?.toUpperCase() === "ACTIVO"
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-red-100 text-red-700"
                }`}
              >
                {c.estado_actual}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

function SeccionCambiosDomicilio({ cambios }) {
  return (
    <section className="mt-6 max-w-5xl rounded-2xl border border-red-200 bg-red-50 p-5 animate-fade-in-up">
      <div className="flex items-center gap-2 text-red-700">
        <AlertTriangle size={17} strokeWidth={1.5} />
        <h2 className="text-sm font-bold uppercase tracking-wide">Cambios de domicilio fiscal</h2>
      </div>
      <p className="mt-1 text-xs text-red-600/80">
        Puede afectar la declaracion de impuestos -- revisa estas empresas.
      </p>
      <div className="mt-3 divide-y divide-red-100">
        {cambios.map((c) => (
          <Link
            key={c.empresa_id}
            href={`/empresas/${c.empresa_id}`}
            className="-mx-2 flex items-center justify-between gap-3 rounded-lg px-2 py-3 transition-colors duration-300 ease-out hover:bg-white/70"
          >
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-ink">{c.empresa_razon_social}</div>
              <div className="text-xs text-slate-500">
                {c.empresa_ruc} &middot; {new Date(c.actualizada_en).toLocaleDateString()}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <span className="text-xs font-medium text-slate-400">{c.condicion_anterior || "?"}</span>
              <ArrowRight size={12} strokeWidth={1.5} className="text-slate-400" />
              <span
                className={`rounded-md px-2 py-0.5 text-[11px] font-bold ${
                  c.condicion_actual === "Habido" ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"
                }`}
              >
                {c.condicion_actual}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

function SeccionProximosVencimientos({ vencimientos }) {
  return (
    <section className="mt-6 max-w-5xl rounded-2xl border border-amber-200 bg-amber-50 p-5 animate-fade-in-up">
      <div className="flex items-center gap-2 text-amber-700">
        <CalendarClock size={17} strokeWidth={1.5} />
        <h2 className="text-sm font-bold uppercase tracking-wide">Proximos vencimientos</h2>
      </div>
      <p className="mt-1 text-xs text-amber-600/80">
        Segun el cronograma oficial de SUNAT (IGV-Renta/PLAME) -- ver el modulo Cronograma para el calendario completo.
      </p>
      <div className="mt-3 divide-y divide-amber-100">
        {vencimientos.map((v) => (
          <Link
            key={`${v.empresa_id}-${v.periodo_tributario}`}
            href={`/empresas/${v.empresa_id}`}
            className="-mx-2 flex items-center justify-between gap-3 rounded-lg px-2 py-3 transition-colors duration-300 ease-out hover:bg-white/70"
          >
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-ink">{v.empresa_razon_social}</div>
              <div className="text-xs text-slate-500">
                {v.empresa_ruc} &middot; periodo {v.periodo_tributario} &middot;{" "}
                {new Date(v.fecha_vencimiento).toLocaleDateString("es-PE", { timeZone: "UTC" })}
              </div>
            </div>
            <span
              className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-bold ${
                v.dias_restantes <= 3 ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"
              }`}
            >
              {v.dias_restantes === 0 ? "Hoy" : v.dias_restantes === 1 ? "Manana" : `en ${v.dias_restantes} dias`}
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}

function SeccionEmpresasConPendientes({ empresas }) {
  return (
    <section>
      <h2 className="flex items-center gap-1.5 text-sm font-bold uppercase tracking-wide text-slate-500">
        <Inbox size={14} strokeWidth={1.75} className="text-slate-400" />
        Empresas con pendientes
      </h2>

      {empresas.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">No hay mensajes pendientes en ninguna empresa. Todo al dia.</p>
      ) : (
        <div className="surface-card mt-3 divide-y divide-slate-100 overflow-hidden">
          {empresas.map((e) => (
            <Link
              key={e.id}
              href={`/empresas/${e.id}`}
              className="flex items-center justify-between border-l-2 border-transparent px-5 py-3.5 transition-all duration-300 ease-out hover:border-accent hover:bg-slate-50"
            >
              <div>
                <div className="text-sm font-medium text-ink">{e.razon_social}</div>
                <div className="text-xs text-slate-500">{e.ruc}</div>
              </div>
              <div className="flex items-center gap-3">
                <span className="rounded-full bg-accent-light px-2 py-0.5 text-[11px] font-bold text-accent">
                  {e.pendientes}
                </span>
                <ArrowRight size={14} strokeWidth={1.5} className="text-slate-400" />
              </div>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

function SeccionActividadReciente({ actividad }) {
  return (
    <section>
      <h2 className="flex items-center gap-1.5 text-sm font-bold uppercase tracking-wide text-slate-500">
        <Activity size={14} strokeWidth={1.75} className="text-slate-400" />
        Actividad reciente
      </h2>

      {actividad.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">Todavia no se ha corrido ninguna consulta.</p>
      ) : (
        <div className="surface-card mt-3 divide-y divide-slate-100 overflow-hidden">
          {actividad.map((a, i) => (
            <Link
              key={i}
              href={`/empresas/${a.empresa_id}`}
              className="flex items-center justify-between border-l-2 border-transparent px-5 py-3.5 transition-all duration-300 ease-out hover:border-accent hover:bg-slate-50"
            >
              <div className="flex items-center gap-3">
                {a.estado === "error" ? (
                  <XCircle size={16} strokeWidth={1.5} className="shrink-0 text-red-500" />
                ) : (
                  <CheckCircle2 size={16} strokeWidth={1.5} className="shrink-0 text-emerald-500" />
                )}
                <div>
                  <div className="text-sm font-medium text-ink">
                    {a.empresa_ruc} - {a.empresa_razon_social}
                  </div>
                  <div className="text-xs text-slate-500">
                    {a.estado === "error"
                      ? a.error || "Error desconocido"
                      : `${a.mensajes_nuevos} mensaje(s) nuevo(s)`}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1.5 text-xs text-slate-400">
                <Activity size={12} strokeWidth={1.5} />
                {a.finalizado_en ? new Date(a.finalizado_en).toLocaleString() : "-"}
              </div>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
