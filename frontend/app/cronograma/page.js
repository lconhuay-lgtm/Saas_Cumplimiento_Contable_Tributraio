"use client";
import { useEffect, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ChevronLeft, ChevronRight, RefreshCw, Loader2, CalendarDays, Building2, X } from "lucide-react";
import Sidebar from "../../components/Sidebar";
import { api, getToken } from "../../lib/api";

const NOMBRES_MES = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];
const NOMBRES_DIA_SEMANA = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"];

const NOMBRES_GRUPO = {
  "0": "RUC termina en 0",
  "1": "RUC termina en 1",
  "2_3": "RUC termina en 2 o 3",
  "4_5": "RUC termina en 4 o 5",
  "6_7": "RUC termina en 6 o 7",
  "8_9": "RUC termina en 8 o 9",
  buenos_contribuyentes: "Buen Contribuyente / UESP",
};

// Un color de chip por grupo -- asi el calendario se lee de un vistazo
// (mismo color = mismo grupo de RUC vence ese dia), similar a como el
// competidor pinta cada evento en su calendario.
const COLOR_GRUPO = {
  "0": "bg-blue-100 text-blue-700",
  "1": "bg-indigo-100 text-indigo-700",
  "2_3": "bg-violet-100 text-violet-700",
  "4_5": "bg-fuchsia-100 text-fuchsia-700",
  "6_7": "bg-rose-100 text-rose-700",
  "8_9": "bg-orange-100 text-orange-700",
  buenos_contribuyentes: "bg-emerald-100 text-emerald-700",
};

// Tareas creadas a mano (p.ej. desde una notificacion del buzon) no tienen
// grupo de RUC -- se pintan aparte para distinguirlas de un vencimiento
// oficial del cronograma SUNAT de un vistazo.
const COLOR_TAREA = "bg-amber-100 text-amber-700";

// Cuantos chips de empresa mostrar dentro de la celda del dia antes de
// resumir el resto en "+N mas" -- mas de esto y la grilla se vuelve
// ilegible en pantallas chicas.
const CHIPS_VISIBLES_POR_DIA = 3;

// Las fechas de vencimiento vienen del backend como medianoche UTC del dia
// calendario correspondiente (ver backend/app/cronograma_sunat.py) -- hay
// que leerlas con los getters UTC, no los locales, porque Peru es UTC-5 y
// un new Date(...).getDate() corriria la fecha un dia hacia atras.
function diaDe(fechaIso) {
  return new Date(fechaIso).getUTCDate();
}

export default function CronogramaPage() {
  const router = useRouter();
  const hoy = useMemo(() => new Date(), []);
  const [anio, setAnio] = useState(hoy.getFullYear());
  const [mes, setMes] = useState(hoy.getMonth() + 1); // 1-12
  const [vencimientos, setVencimientos] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [sincronizando, setSincronizando] = useState(false);
  const [diaSeleccionado, setDiaSeleccionado] = useState(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anio, mes]);

  async function cargar() {
    setCargando(true);
    setError("");
    setDiaSeleccionado(null);
    try {
      // Rango del mes en UTC, mismo criterio que usa el backend para las
      // fechas de vencimiento (ver backend/app/cronograma_sunat.py).
      const inicioMes = new Date(Date.UTC(anio, mes - 1, 1)).toISOString();
      const finMes = new Date(Date.UTC(mes === 12 ? anio + 1 : anio, mes === 12 ? 0 : mes, 1)).toISOString();

      const [dataCronograma, dataTareas] = await Promise.all([
        api.obtenerAgendaMes(anio, mes),
        // Tareas sueltas con fecha propia (p.ej. creadas desde una
        // notificacion del buzon) -- nutren el calendario ademas del
        // cronograma oficial. Si falla, el calendario sigue mostrando el
        // cronograma igual (no es critico).
        api.listarTareas({ fechaDesde: inicioMes, fechaHasta: finMes }).catch(() => []),
      ]);

      const itemsCronograma = dataCronograma.vencimientos.map((v) => ({
        tipoItem: "cronograma",
        key: `c-${v.empresa_id}-${v.periodo_tributario}`,
        fecha_vencimiento: v.fecha_vencimiento,
        empresa_id: v.empresa_id,
        empresa_ruc: v.empresa_ruc,
        empresa_razon_social: v.empresa_razon_social,
        periodo_tributario: v.periodo_tributario,
        grupo: v.grupo,
      }));
      const itemsTareas = dataTareas
        .filter((t) => t.fecha_vencimiento)
        .map((t) => ({
          tipoItem: "tarea",
          key: `t-${t.id}`,
          fecha_vencimiento: t.fecha_vencimiento,
          empresa_id: t.empresa_id,
          empresa_ruc: t.empresa_ruc,
          empresa_razon_social: t.empresa_razon_social,
          titulo: t.titulo,
          prioridad: t.prioridad,
        }));

      setVencimientos([...itemsCronograma, ...itemsTareas]);
    } catch (err) {
      setError(err.message);
    } finally {
      setCargando(false);
    }
  }

  async function sincronizar() {
    setSincronizando(true);
    try {
      const resultado = await api.sincronizarCronograma(anio);
      alert(
        `Cronograma ${resultado.anio} sincronizado: ${resultado.periodos_procesados} periodo(s), ${resultado.filas_guardadas} fila(s).`
      );
      await cargar();
    } catch (err) {
      alert(err.message);
    } finally {
      setSincronizando(false);
    }
  }

  function irMesAnterior() {
    if (mes === 1) {
      setMes(12);
      setAnio((a) => a - 1);
    } else {
      setMes((m) => m - 1);
    }
  }
  function irMesSiguiente() {
    if (mes === 12) {
      setMes(1);
      setAnio((a) => a + 1);
    } else {
      setMes((m) => m + 1);
    }
  }
  function irHoy() {
    setAnio(hoy.getFullYear());
    setMes(hoy.getMonth() + 1);
  }

  const porDia = useMemo(() => {
    const mapa = {};
    for (const v of vencimientos) {
      const d = diaDe(v.fecha_vencimiento);
      (mapa[d] = mapa[d] || []).push(v);
    }
    return mapa;
  }, [vencimientos]);

  // Matriz de celdas del mes -- la semana empieza en lunes (convencion
  // peruana/hispana). getUTCDay() de JS da 0=domingo..6=sabado, se
  // convierte a 0=lunes..6=domingo con (dia + 6) % 7.
  const celdas = useMemo(() => {
    const primerDia = new Date(Date.UTC(anio, mes - 1, 1));
    const diasEnMes = new Date(Date.UTC(anio, mes, 0)).getUTCDate();
    const offset = (primerDia.getUTCDay() + 6) % 7;
    const lista = [];
    for (let i = 0; i < offset; i++) lista.push(null);
    for (let d = 1; d <= diasEnMes; d++) lista.push(d);
    while (lista.length % 7 !== 0) lista.push(null);
    return lista;
  }, [anio, mes]);

  const esHoy = (d) => d != null && anio === hoy.getFullYear() && mes === hoy.getMonth() + 1 && d === hoy.getDate();

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 py-8 xl:px-12">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-ink">Cronograma</h1>
            <p className="mt-1 text-sm text-slate-600">
              Vencimientos de declaracion mensual (IGV-Renta/PLAME) segun el cronograma oficial de SUNAT
            </p>
          </div>
          <button
            onClick={sincronizar}
            disabled={sincronizando}
            title="Vuelve a descargar el cronograma oficial de SUNAT para este anio (por si hubo una modificacion, p.ej. una prorroga)"
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition-all duration-300 ease-out hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {sincronizando ? (
              <Loader2 size={15} strokeWidth={1.5} className="animate-spin" />
            ) : (
              <RefreshCw size={15} strokeWidth={1.5} />
            )}
            Sincronizar {anio}
          </button>
        </div>

        {error && (
          <div className="mt-6 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
        )}

        <div className="surface-card mt-6 p-6">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <button
                onClick={irMesAnterior}
                className="flex items-center justify-center rounded-lg p-1.5 text-slate-500 transition-colors duration-300 ease-out hover:bg-slate-100 hover:text-ink"
                aria-label="Mes anterior"
              >
                <ChevronLeft size={18} strokeWidth={1.5} />
              </button>
              <h2 className="w-44 text-center text-base font-bold text-ink">
                {NOMBRES_MES[mes - 1]} {anio}
              </h2>
              <button
                onClick={irMesSiguiente}
                className="flex items-center justify-center rounded-lg p-1.5 text-slate-500 transition-colors duration-300 ease-out hover:bg-slate-100 hover:text-ink"
                aria-label="Mes siguiente"
              >
                <ChevronRight size={18} strokeWidth={1.5} />
              </button>
            </div>
            <button
              onClick={irHoy}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition-all duration-300 ease-out hover:border-accent hover:text-accent"
            >
              Hoy
            </button>
          </div>

          {cargando ? (
            <p className="mt-8 text-sm text-slate-500">Cargando...</p>
          ) : (
            <>
              <div className="mt-5 grid grid-cols-7 gap-1.5">
                {NOMBRES_DIA_SEMANA.map((n) => (
                  <div
                    key={n}
                    className="pb-1 text-center text-[11px] font-semibold uppercase tracking-wide text-slate-400"
                  >
                    {n}
                  </div>
                ))}
                {celdas.map((d, i) => {
                  const items = d != null ? porDia[d] || [] : [];
                  const seleccionada = diaSeleccionado === d;
                  const visibles = items.slice(0, CHIPS_VISIBLES_POR_DIA);
                  const restantes = items.length - visibles.length;
                  return (
                    <button
                      key={i}
                      disabled={d == null || items.length === 0}
                      onClick={() => setDiaSeleccionado(d)}
                      className={`flex min-h-[112px] flex-col items-stretch gap-1 rounded-lg border p-2 text-left transition-all duration-300 ease-out ${
                        d == null
                          ? "border-transparent"
                          : items.length > 0
                          ? seleccionada
                            ? "border-accent bg-accent-light/40"
                            : "border-slate-200 bg-white hover:-translate-y-0.5 hover:border-accent hover:shadow-soft"
                          : "border-transparent"
                      }`}
                    >
                      {d != null && (
                        <span
                          className={`self-start text-xs font-bold ${
                            esHoy(d)
                              ? "flex h-5 w-5 items-center justify-center rounded-full bg-accent text-white"
                              : items.length > 0
                              ? "text-ink"
                              : "text-slate-400"
                          }`}
                        >
                          {d}
                        </span>
                      )}
                      {items.length > 0 && (
                        <div className="mt-0.5 flex flex-col gap-1">
                          {visibles.map((v) => (
                            <span
                              key={v.key}
                              title={v.tipoItem === "tarea" ? v.titulo : v.empresa_razon_social}
                              className={`truncate rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                                v.tipoItem === "tarea" ? COLOR_TAREA : COLOR_GRUPO[v.grupo] || "bg-slate-100 text-slate-600"
                              }`}
                            >
                              {v.empresa_razon_social}
                            </span>
                          ))}
                          {restantes > 0 && (
                            <span className="text-[10px] font-semibold text-accent">+{restantes} mas</span>
                          )}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>

              {vencimientos.length === 0 && (
                <p className="mt-6 text-sm text-slate-500">
                  Sin vencimientos cargados para este mes. Si es la primera vez que usas este modulo, presiona
                  &quot;Sincronizar {anio}&quot; arriba.
                </p>
              )}
            </>
          )}
        </div>

        {diaSeleccionado != null && (porDia[diaSeleccionado]?.length || 0) > 0 && (
          <div className="surface-card mt-6 p-6">
            <div className="flex items-center justify-between">
              <h3 className="flex items-center gap-1.5 text-sm font-bold uppercase tracking-wide text-slate-500">
                <CalendarDays size={14} strokeWidth={1.75} className="text-slate-400" />
                Vence el {diaSeleccionado} de {NOMBRES_MES[mes - 1]}
              </h3>
              <button
                onClick={() => setDiaSeleccionado(null)}
                className="flex items-center justify-center rounded-lg p-1.5 text-slate-400 transition-colors duration-300 ease-out hover:bg-slate-100 hover:text-ink"
                aria-label="Cerrar"
              >
                <X size={16} strokeWidth={1.5} />
              </button>
            </div>
            <div className="mt-3 divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-100">
              {porDia[diaSeleccionado].map((v) => (
                <Link
                  key={v.key}
                  href={`/empresas/${v.empresa_id}`}
                  className="flex items-center justify-between gap-3 px-5 py-3.5 transition-all duration-300 ease-out hover:bg-slate-50"
                >
                  <div className="flex items-center gap-3">
                    <Building2 size={15} strokeWidth={1.5} className="shrink-0 text-slate-400" />
                    <div>
                      <div className="text-sm font-medium text-ink">
                        {v.tipoItem === "tarea" ? v.titulo : v.empresa_razon_social}
                      </div>
                      <div className="text-xs text-slate-500">
                        {v.tipoItem === "tarea"
                          ? `${v.empresa_razon_social} (${v.empresa_ruc})`
                          : `${v.empresa_ruc} · periodo ${v.periodo_tributario}`}
                      </div>
                    </div>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                      v.tipoItem === "tarea" ? COLOR_TAREA : COLOR_GRUPO[v.grupo] || "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {v.tipoItem === "tarea" ? "Tarea" : NOMBRES_GRUPO[v.grupo] || v.grupo}
                  </span>
                </Link>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
