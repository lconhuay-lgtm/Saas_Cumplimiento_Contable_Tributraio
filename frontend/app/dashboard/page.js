"use client";
import { useEffect, useMemo, useRef, useState } from "react";
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
  AlarmClock,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import Sidebar from "../../components/Sidebar";
import { api, getToken } from "../../lib/api";
import BotonConsultarTodas, { formatoDuracionEstimada } from "../../components/BotonConsultarTodas";
import { useTrabajos } from "../../contexts/TrabajosContext";

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
  const [consultandoTodas, setConsultandoTodas] = useState(false);
  const { estadoMasiva } = useTrabajos();
  const masivaEnCursoAnteriorRef = useRef(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // El poll de GET /consultas/estado y el dialogo de resumen final ahora
  // viven en TrabajosContext (persisten aunque el usuario navegue a otra
  // pantalla o cierre esta pestana -- ver ese archivo). Aca solo queda
  // refrescar el resumen del dashboard cuando una tanda que estaba en
  // curso termina.
  useEffect(() => {
    if (masivaEnCursoAnteriorRef.current && estadoMasiva && !estadoMasiva.en_curso) {
      cargar();
    }
    if (estadoMasiva) masivaEnCursoAnteriorRef.current = estadoMasiva.en_curso;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [estadoMasiva]);

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

  async function consultarTodas() {
    const cantidad = resumen?.empresas_activas || 0;
    if (
      !confirm(
        `Esto va a consultar en vivo las ${cantidad} empresa(s) activa(s), espaciadas ~45s entre si para no sobrecargar SUNAT -- tiempo estimado total: ${formatoDuracionEstimada(cantidad)}. No hace falta dejar esta pantalla abierta, se sigue procesando igual. Continuar?`
      )
    ) {
      return;
    }
    setConsultandoTodas(true);
    try {
      const resultado = await api.consultarTodas();
      alert(
        `${resultado.empresas_encoladas} empresa(s) encoladas` +
          (resultado.saltadas_sin_credencial > 0
            ? `, ${resultado.saltadas_sin_credencial} salteada(s) por falta de credenciales.`
            : ".") +
          ` Tiempo estimado total: ${formatoDuracionEstimada(resultado.empresas_encoladas, resultado.espaciado_seg)}. ` +
          "Se iran procesando de a poco -- el boton va a mostrar el avance (X/Y) mientras tanto."
      );
      await cargar();
    } catch (err) {
      alert(err.message);
    } finally {
      setConsultandoTodas(false);
    }
  }

  const ultimaSincronizacion = resumen?.actividad_reciente?.[0];

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 pb-8 pt-24 xl:px-12">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-ink">Dashboard</h1>
            <p className="mt-1 text-sm text-slate-600">
              {resumen ? `${resumen.empresas_activas} de ${resumen.empresas_totales} empresas activas` : "Resumen general de todas tus empresas monitoreadas"}
            </p>
          </div>
          <BotonConsultarTodas
            onClick={consultarTodas}
            consultando={consultandoTodas}
            estado={estadoMasiva}
            disabled={!resumen || resumen.empresas_totales === 0}
          />
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
            <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
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
                Icon={AlarmClock}
                color="red"
                label="Tareas vencidas"
                value={resumen.tareas_vencidas || 0}
                detalle="Sin completar, fecha pasada"
                href="/tareas?estado=vencida"
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

            {(resumen.cambios_estado_contribuyente_recientes.length > 0 ||
              resumen.cambios_domicilio_recientes.length > 0 ||
              resumen.proximos_vencimientos?.length > 0 ||
              resumen.tareas_completadas_recientes?.length > 0) && (
              // Flex en vez de grid a proposito: con grid, una fila le copia
              // la altura al item mas alto de ESA fila en AMBAS columnas, asi
              // que una seccion corta (ej. 4 cambios de domicilio) quedaba
              // estirada a la fuerza hasta igualar a "Proximos vencimientos"
              // (que puede traer decenas), dejando un hueco vacio enorme
              // abajo -- de ahi que se viera "sumamente grande" aunque tuviera
              // pocos items. Con 2 columnas flex independientes cada una
              // ocupa solo lo que necesita, y se aprovecha el espacio
              // sobrante apilando "Tareas completadas recientemente" debajo
              // de Domicilio en vez de dejarlo en blanco.
              <div className="mt-6 flex flex-col gap-6 xl:flex-row xl:items-start">
                <div className="flex flex-1 flex-col gap-6">
                  {resumen.cambios_domicilio_recientes.length > 0 && (
                    <SeccionCambiosDomicilio cambios={resumen.cambios_domicilio_recientes} />
                  )}
                  {resumen.tareas_completadas_recientes?.length > 0 && (
                    <SeccionTareasCompletadas tareas={resumen.tareas_completadas_recientes} />
                  )}
                </div>
                <div className="flex flex-1 flex-col gap-6">
                  {resumen.cambios_estado_contribuyente_recientes.length > 0 && (
                    <SeccionCambiosEstadoContribuyente cambios={resumen.cambios_estado_contribuyente_recientes} />
                  )}
                  {resumen.proximos_vencimientos?.length > 0 && (
                    <SeccionProximosVencimientos vencimientos={resumen.proximos_vencimientos} />
                  )}
                </div>
              </div>
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
  red: "bg-red-600",
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
            Tareas del periodo elegido (IGV-Renta, Planilla, AFP, SBS y demas obligaciones) -- cambia el mes
            arriba para ver otros periodos.
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
      <div className="grid grid-cols-3 gap-2 p-4">
        <div>
          <div className="text-2xl font-extrabold text-ink">{item.total}</div>
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Total</div>
        </div>
        <div>
          <div className="text-2xl font-extrabold text-emerald-600">{item.completados}</div>
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Completados</div>
        </div>
        <div>
          <div className={`text-2xl font-extrabold ${item.vencidas > 0 ? "text-red-600" : "text-slate-300"}`}>
            {item.vencidas}
          </div>
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Vencidas</div>
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
  const { paginaSegura, totalPaginas, itemsPagina, setPagina } = usePaginacion(cambios, POR_PAGINA_PENDIENTES);
  return (
    <section className="rounded-2xl border border-red-200 bg-red-50 p-5 animate-fade-in-up">
      <div className="flex items-center gap-2 text-red-700">
        <AlertTriangle size={17} strokeWidth={1.5} />
        <h2 className="text-sm font-bold uppercase tracking-wide">Cambios de estado del contribuyente</h2>
      </div>
      <p className="mt-1 text-xs text-red-600/80">
        Puede afectar la declaracion de impuestos -- revisa estas empresas.
      </p>
      <div className="mt-3 divide-y divide-red-100">
        {itemsPagina.map((c) => (
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
      <ControlesPaginacion paginaSegura={paginaSegura} totalPaginas={totalPaginas} total={cambios.length} setPagina={setPagina} />
    </section>
  );
}

function SeccionCambiosDomicilio({ cambios }) {
  const { paginaSegura, totalPaginas, itemsPagina, setPagina } = usePaginacion(cambios, POR_PAGINA_PENDIENTES);
  return (
    <section className="rounded-2xl border border-red-200 bg-red-50 p-5 animate-fade-in-up">
      <div className="flex items-center gap-2 text-red-700">
        <AlertTriangle size={17} strokeWidth={1.5} />
        <h2 className="text-sm font-bold uppercase tracking-wide">Cambios de domicilio fiscal</h2>
      </div>
      <p className="mt-1 text-xs text-red-600/80">
        Puede afectar la declaracion de impuestos -- revisa estas empresas.
      </p>
      <div className="mt-3 divide-y divide-red-100">
        {itemsPagina.map((c) => (
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
      <ControlesPaginacion paginaSegura={paginaSegura} totalPaginas={totalPaginas} total={cambios.length} setPagina={setPagina} />
    </section>
  );
}

const ETIQUETAS_TIPO_TAREA = {
  igv_renta: "IGV-Renta",
  planilla: "Planilla",
  afp: "AFP",
  sbs: "Reporte SBS",
  cts: "CTS",
  itan: "ITAN",
  sire: "SIRE",
  otro: "Otro",
};

function SeccionTareasCompletadas({ tareas }) {
  const { paginaSegura, totalPaginas, itemsPagina, setPagina } = usePaginacion(tareas, POR_PAGINA_PENDIENTES);
  return (
    <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 animate-fade-in-up">
      <div className="flex items-center gap-2 text-emerald-700">
        <CheckCircle2 size={17} strokeWidth={1.5} />
        <h2 className="text-sm font-bold uppercase tracking-wide">Tareas completadas recientemente</h2>
      </div>
      <p className="mt-1 text-xs text-emerald-600/80">
        Las ultimas obligaciones marcadas como completadas, de cualquier periodo.
      </p>
      <div className="mt-3 divide-y divide-emerald-100">
        {itemsPagina.map((t) => (
          <Link
            key={t.id}
            href={`/empresas/${t.empresa_id}`}
            className="-mx-2 flex items-center justify-between gap-3 rounded-lg px-2 py-3 transition-colors duration-300 ease-out hover:bg-white/70"
          >
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-ink">{t.titulo}</div>
              <div className="truncate text-xs text-slate-500">
                {t.empresa_razon_social} &middot; {t.empresa_ruc}
              </div>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
              <span className="rounded-md bg-emerald-100 px-2 py-0.5 text-[11px] font-bold text-emerald-700">
                {ETIQUETAS_TIPO_TAREA[t.tipo] || t.tipo}
              </span>
              <span className="text-[11px] text-slate-400">
                {new Date(t.fecha_completado).toLocaleDateString()}
              </span>
            </div>
          </Link>
        ))}
      </div>
      <ControlesPaginacion paginaSegura={paginaSegura} totalPaginas={totalPaginas} total={tareas.length} setPagina={setPagina} />
    </section>
  );
}

// Paginacion del lado del cliente -- a pedido: estas listas pueden crecer
// mucho (muchas empresas, muchos vencimientos proximos, mucha actividad) y
// antes se mostraban completas, empujando el resto de la pantalla hacia
// abajo sin limite. Se cortan en paginas de 15 (mismo patron en las 3
// secciones del Dashboard y en la paginacion de mensajes de
// empresas/[id]/page.js). El backend ya manda la lista completa (ordenada
// segun corresponda a cada seccion -- ver routers/dashboard.py), asi que
// alcanza con recortarla aca, no hace falta pedirle paginas al backend.
const POR_PAGINA_PENDIENTES = 10;
const POR_PAGINA_VENCIMIENTOS = 10;
const POR_PAGINA_ACTIVIDAD = 10;

// Hook compartido por las 3 secciones paginadas del Dashboard -- evita
// repetir el mismo calculo de pagina/totalPaginas/slice en cada una.
function usePaginacion(lista, porPagina) {
  const [pagina, setPagina] = useState(1);
  const totalPaginas = Math.max(1, Math.ceil(lista.length / porPagina));
  const paginaSegura = Math.min(pagina, totalPaginas);
  const itemsPagina = lista.slice((paginaSegura - 1) * porPagina, paginaSegura * porPagina);
  return { paginaSegura, totalPaginas, itemsPagina, setPagina };
}

function ControlesPaginacion({ paginaSegura, totalPaginas, total, setPagina }) {
  if (totalPaginas <= 1) return null;
  return (
    <div className="mt-3 flex items-center justify-between gap-2 text-xs text-slate-500">
      <button
        onClick={() => setPagina((p) => Math.max(1, p - 1))}
        disabled={paginaSegura <= 1}
        className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 font-medium text-slate-600 hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
      >
        <ChevronLeft size={13} strokeWidth={1.5} />
        Anterior
      </button>
      <span>
        Pagina {paginaSegura} de {totalPaginas} ({total} en total)
      </span>
      <button
        onClick={() => setPagina((p) => Math.min(totalPaginas, p + 1))}
        disabled={paginaSegura >= totalPaginas}
        className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 font-medium text-slate-600 hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
      >
        Siguiente
        <ChevronRight size={13} strokeWidth={1.5} />
      </button>
    </div>
  );
}

function SeccionProximosVencimientos({ vencimientos }) {
  const { paginaSegura, totalPaginas, itemsPagina, setPagina } = usePaginacion(vencimientos, POR_PAGINA_VENCIMIENTOS);
  return (
    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 animate-fade-in-up">
      <div className="flex items-center gap-2 text-amber-700">
        <CalendarClock size={17} strokeWidth={1.5} />
        <h2 className="text-sm font-bold uppercase tracking-wide">Proximos vencimientos</h2>
      </div>
      <p className="mt-1 text-xs text-amber-600/80">
        Segun el cronograma oficial de SUNAT (IGV-Renta/PLAME) -- ver el modulo Cronograma para el calendario completo.
      </p>
      <div className="mt-3 divide-y divide-amber-100">
        {itemsPagina.map((v) => (
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
      <ControlesPaginacion
        paginaSegura={paginaSegura}
        totalPaginas={totalPaginas}
        total={vencimientos.length}
        setPagina={setPagina}
      />
    </section>
  );
}

function SeccionEmpresasConPendientes({ empresas }) {
  const { paginaSegura, totalPaginas, itemsPagina, setPagina } = usePaginacion(empresas, POR_PAGINA_PENDIENTES);

  return (
    <section>
      <h2 className="flex items-center gap-1.5 text-sm font-bold uppercase tracking-wide text-slate-500">
        <Inbox size={14} strokeWidth={1.75} className="text-slate-400" />
        Empresas con pendientes
      </h2>

      {empresas.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">No hay mensajes pendientes en ninguna empresa. Todo al dia.</p>
      ) : (
        <>
          <div className="surface-card mt-3 divide-y divide-slate-100 overflow-hidden">
            {itemsPagina.map((e) => (
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

          <ControlesPaginacion
            paginaSegura={paginaSegura}
            totalPaginas={totalPaginas}
            total={empresas.length}
            setPagina={setPagina}
          />
        </>
      )}
    </section>
  );
}

function SeccionActividadReciente({ actividad }) {
  // El backend ya limita esto a los ultimos 10 jobs (ver routers/dashboard.py),
  // asi que estos controles normalmente no van a aparecer -- se dejan aca
  // igual, por consistencia con las otras 2 secciones paginadas y por si
  // ese limite crece mas adelante.
  const { paginaSegura, totalPaginas, itemsPagina, setPagina } = usePaginacion(actividad, POR_PAGINA_ACTIVIDAD);

  return (
    <section>
      <h2 className="flex items-center gap-1.5 text-sm font-bold uppercase tracking-wide text-slate-500">
        <Activity size={14} strokeWidth={1.75} className="text-slate-400" />
        Actividad reciente
      </h2>

      {actividad.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">Todavia no se ha corrido ninguna consulta.</p>
      ) : (
        <>
        <div className="surface-card mt-3 divide-y divide-slate-100 overflow-hidden">
          {itemsPagina.map((a, i) => (
            <Link
              key={`${a.empresa_id}-${a.finalizado_en}-${i}`}
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
        <ControlesPaginacion
          paginaSegura={paginaSegura}
          totalPaginas={totalPaginas}
          total={actividad.length}
          setPagina={setPagina}
        />
        </>
      )}
    </section>
  );
}
