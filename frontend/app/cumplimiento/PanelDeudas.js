"use client";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Download,
  Gavel,
  Loader2,
  RefreshCw,
  Search,
} from "lucide-react";
import { api } from "../../lib/api";
import { descargarCsv } from "./utilidades";

const FILTROS = [
  { id: "con_deuda", label: "Con deuda vigente" },
  { id: "coactiva", label: "En cobranza coactiva" },
  { id: "sin_deuda", label: "Sin deuda" },
  { id: "todas", label: "Todas" },
];

const EVENTOS = {
  nuevo: "Aparecio",
  cambio_etapa: "Cambio de etapa",
  cambio_saldo: "Cambio de saldo",
  ya_no_aparece: "Ya no aparece en SUNAT",
  reaparecio: "Volvio a aparecer",
};

const soles = new Intl.NumberFormat("es-PE", { style: "currency", currency: "PEN" });

// "2026-09-23" -> "23/09/2026" sin pasar por Date (evita correrse un dia por zona horaria).
function fechaIso(valor) {
  if (!valor) return "—";
  const [a, m, d] = valor.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

function fechaHora(valor) {
  return valor ? new Date(valor).toLocaleDateString("es-PE") : "—";
}

function textoHistorial(v) {
  return (v.historial || [])
    .map((h) => `${fechaHora(h.fecha)}: ${EVENTOS[h.evento] || h.evento}${h.detalle ? ` (${h.detalle})` : ""}`)
    .join("\n");
}

function resumirEmpresa(f) {
  const vigentes = f.valores.filter((v) => v.vigente);
  const coactiva = vigentes.filter((v) => v.en_cobranza_coactiva);
  return {
    ...f,
    vigentes,
    historicos: f.valores.filter((v) => !v.vigente),
    saldo: vigentes.reduce((s, v) => s + v.saldo_total, 0),
    coactiva,
    saldoCoactiva: coactiva.reduce((s, v) => s + v.saldo_total, 0),
  };
}

// enfoque: {empresaId, valores: [num_valor]} | null -- viene de la ventana de
// "Nuevas deudas en SUNAT": abre esa empresa, resalta esos valores y baja hasta ahi.
export default function PanelDeudas({ enfoque = null }) {
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [filtro, setFiltro] = useState("con_deuda");
  const [busqueda, setBusqueda] = useState("");
  const [verHistorial, setVerHistorial] = useState(false);
  const [abiertas, setAbiertas] = useState({});
  const [encolando, setEncolando] = useState(false);
  const enfoqueDesplazado = useRef(null);

  useEffect(() => {
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!enfoque) return;
    setFiltro("todas");
    setBusqueda("");
    setAbiertas((a) => ({ ...a, [enfoque.empresaId]: true }));
    enfoqueDesplazado.current = null;
    cargar({ silencioso: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enfoque]);

  useEffect(() => {
    if (!enfoque || !datos || enfoqueDesplazado.current === enfoque) return;
    const fila = document.getElementById(`deudas-empresa-${enfoque.empresaId}`);
    if (fila) {
      fila.scrollIntoView({ behavior: "smooth", block: "start" });
      enfoqueDesplazado.current = enfoque;
    }
  }, [enfoque, datos, filtro]);

  const hayConsultasEnCurso = !!datos?.filas.some((f) => f.consulta_en_curso);
  useEffect(() => {
    if (!hayConsultasEnCurso) return;
    const t = setInterval(() => cargar({ silencioso: true }), 10000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hayConsultasEnCurso]);

  async function cargar({ silencioso = false } = {}) {
    if (!silencioso) setCargando(true);
    try {
      setDatos(await api.obtenerCumplimientoDeudas());
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
      const r = await api.consultarDeudasTodas();
      setAviso(
        r.empresas_encoladas
          ? `Se leeran las deudas de ${r.empresas_encoladas} empresa(s) en SUNAT, una cada ${r.espaciado_seg} s. La tabla se ira actualizando sola.`
          : "No hay empresas para consultar (todas estan en curso o sin credenciales SOL)."
      );
      cargar({ silencioso: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setEncolando(false);
    }
  }

  async function consultarUna(empresaId) {
    try {
      await api.consultarDeudas(empresaId);
      cargar({ silencioso: true });
    } catch (err) {
      setError(err.message);
    }
  }

  const empresas = useMemo(() => (datos ? datos.filas.map(resumirEmpresa) : []), [datos]);

  const totales = useMemo(() => {
    const t = { saldo: 0, valores: 0, coactiva: 0, saldoCoactiva: 0, empresasConDeuda: 0, historicos: 0 };
    empresas.forEach((e) => {
      t.saldo += e.saldo;
      t.valores += e.vigentes.length;
      t.coactiva += e.coactiva.length;
      t.saldoCoactiva += e.saldoCoactiva;
      t.historicos += e.historicos.length;
      if (e.vigentes.length) t.empresasConDeuda += 1;
    });
    return t;
  }, [empresas]);

  const visibles = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    return empresas
      .filter((e) => {
        if (q && !e.razon_social.toLowerCase().includes(q) && !e.ruc.includes(q)) return false;
        if (filtro === "con_deuda") return e.vigentes.length > 0;
        if (filtro === "coactiva") return e.coactiva.length > 0;
        if (filtro === "sin_deuda") return e.vigentes.length === 0;
        return true;
      })
      .sort((a, b) => b.saldo - a.saldo || a.razon_social.localeCompare(b.razon_social));
  }, [empresas, busqueda, filtro]);

  function alternar(empresaId) {
    setAbiertas((a) => ({ ...a, [empresaId]: !a[empresaId] }));
  }

  function exportarCsv() {
    const lineas = [];
    visibles.forEach((e) =>
      (verHistorial ? e.valores : e.vigentes).forEach((v) =>
        lineas.push([
          e.ruc, e.razon_social, v.num_valor, `${v.tipo} ${v.tipo_descripcion}`.trim(), v.periodo,
          `${v.cod_tributo} ${v.tributo}`.trim(), fechaIso(v.fecha_emision), fechaIso(v.fecha_notificacion),
          v.etapa, v.num_expediente_coactivo || "", v.monto_tributo.toFixed(2), v.tributo_pendiente.toFixed(2), v.interes.toFixed(2),
          v.saldo_total.toFixed(2), v.vigente ? "Vigente" : `Ya no aparece desde ${fechaHora(v.ya_no_aparece_desde)}`,
          fechaHora(v.detectado_en),
        ])
      )
    );
    descargarCsv(
      "deudas_valores_pendientes.csv",
      ["RUC", "Razon social", "Nro. valor", "Tipo", "Periodo", "Tributo", "Emision", "Notificacion", "Etapa",
        "Exp. coactivo", "Importe original", "Tributo pendiente", "Interes", "Saldo total", "Situacion", "Detectado el"],
      lineas
    );
  }

  const tarjetas = [
    { titulo: "Deuda vigente total", valor: soles.format(totales.saldo), nota: `${totales.valores} valor(es) pendiente(s)` },
    {
      titulo: "En cobranza coactiva",
      valor: soles.format(totales.saldoCoactiva),
      nota: `${totales.coactiva} valor(es) -- riesgo de embargo`,
      alerta: totales.coactiva > 0,
      filtro: "coactiva",
    },
    { titulo: "Empresas con deuda", valor: `${totales.empresasConDeuda} de ${empresas.length}`, nota: "con al menos un valor pendiente", filtro: "con_deuda" },
    { titulo: "Ya no aparecen", valor: totales.historicos, nota: "pagados, fraccionados o anulados (historial)" },
  ];

  return (
    <>
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-600">
          Valores pendientes de pago (ordenes de pago, multas, resoluciones) de cada empresa desde enero 2020 hasta el
          mes pasado, leidos de SUNAT en "Revision de mis deudas". Se revisa solo todos los dias a las 8:30 a.m. y guarda
          el historial, incluso de las deudas que ya no aparecen.
        </p>
        <div className="flex items-center gap-2">
          <button
            onClick={exportarCsv}
            disabled={!visibles.length}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition-all duration-300 ease-out hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Download size={15} strokeWidth={1.5} />
            Excel
          </button>
          <button
            onClick={consultarTodas}
            disabled={encolando || hayConsultasEnCurso}
            title="Lee de SUNAT los valores pendientes de todas las empresas (una entrada a SUNAT por empresa, espaciadas)"
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

      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tarjetas.map((t) => (
          <button
            key={t.titulo}
            onClick={() => t.filtro && setFiltro(t.filtro)}
            className={`surface-card p-4 text-left transition-all duration-300 ease-out ${t.filtro ? "hover:-translate-y-0.5" : "cursor-default"} ${
              t.filtro && filtro === t.filtro ? "ring-2 ring-accent" : ""
            }`}
          >
            <p className="text-xs font-semibold text-slate-500">{t.titulo}</p>
            <p className={`mt-1 text-2xl font-extrabold ${t.alerta ? "text-red-600" : "text-ink"}`}>{t.valor}</p>
            <p className="mt-0.5 text-xs text-slate-500">{t.nota}</p>
          </button>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-1">
        {FILTROS.map((f) => (
          <button
            key={f.id}
            onClick={() => setFiltro(f.id)}
            className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
              filtro === f.id ? "bg-accent text-white" : "bg-white text-slate-600 hover:bg-slate-100"
            }`}
          >
            {f.label}
          </button>
        ))}
        <label className="ml-3 flex items-center gap-1.5 text-xs font-medium text-slate-600">
          <input type="checkbox" checked={verHistorial} onChange={(e) => setVerHistorial(e.target.checked)} />
          Mostrar tambien las que ya no aparecen
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

      <div className="surface-card mt-4 overflow-x-auto">
        {cargando ? (
          <p className="p-6 text-sm text-slate-500">Cargando...</p>
        ) : !visibles.length ? (
          <p className="p-6 text-sm text-slate-500">
            {empresas.length ? "Ninguna empresa calza con el filtro." : "No hay empresas activas para mostrar."}
          </p>
        ) : (
          <table className="w-full min-w-[900px] border-collapse text-sm">
            <thead>
              <tr className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3 text-left">Empresa / RUC</th>
                <th className="px-3 py-3 text-right">Valores vigentes</th>
                <th className="px-3 py-3 text-right">Deuda vigente</th>
                <th className="px-3 py-3 text-left">Cobranza coactiva</th>
                <th className="px-3 py-3 text-right">Lectura</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {visibles.map((e) => {
                const abierta = !!abiertas[e.empresa_id];
                const lista = verHistorial ? e.valores : e.vigentes;
                const resaltados = enfoque?.empresaId === e.empresa_id ? enfoque.valores : [];
                return (
                  <Fragment key={e.empresa_id}>
                    <tr
                      id={`deudas-empresa-${e.empresa_id}`}
                      className={`cursor-pointer scroll-mt-24 hover:bg-slate-50/60 ${resaltados.length ? "bg-amber-50/60" : ""}`}
                      onClick={() => alternar(e.empresa_id)}
                    >
                      <td className="max-w-[320px] px-4 py-2.5">
                        <div className="flex items-center gap-1.5">
                          {abierta ? <ChevronDown size={14} className="shrink-0 text-slate-400" /> : <ChevronRight size={14} className="shrink-0 text-slate-400" />}
                          <div className="min-w-0">
                            <Link
                              href={`/empresas/${e.empresa_id}`}
                              onClick={(ev) => ev.stopPropagation()}
                              className="block truncate font-semibold text-ink hover:text-accent"
                              title={e.razon_social}
                            >
                              {e.razon_social}
                            </Link>
                            <span className="text-xs text-slate-500">{e.ruc}</span>
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-right font-semibold text-ink">{e.vigentes.length || "—"}</td>
                      <td className={`px-3 py-2.5 text-right font-bold ${e.saldo > 0 ? "text-ink" : "text-slate-400"}`}>
                        {e.saldo > 0 ? soles.format(e.saldo) : "Sin deuda"}
                      </td>
                      <td className="px-3 py-2.5">
                        {e.coactiva.length > 0 ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs font-bold text-red-700">
                            <Gavel size={12} strokeWidth={2} />
                            {e.coactiva.length} valor(es) · {soles.format(e.saldoCoactiva)}
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">No</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-right text-xs text-slate-500" onClick={(ev) => ev.stopPropagation()}>
                        <div className="flex items-center justify-end gap-2">
                          {e.ultimo_error && (
                            <span title={`Ultima lectura fallida: ${e.ultimo_error}`}>
                              <AlertTriangle size={14} strokeWidth={2} className="text-amber-500" />
                            </span>
                          )}
                          <span>{e.actualizado_en ? fechaHora(e.actualizado_en) : "Sin leer"}</span>
                          <button
                            onClick={() => consultarUna(e.empresa_id)}
                            disabled={e.consulta_en_curso}
                            title="Leer las deudas de esta empresa en SUNAT"
                            className="flex items-center justify-center rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-accent disabled:cursor-not-allowed"
                          >
                            {e.consulta_en_curso ? (
                              <Loader2 size={14} strokeWidth={2} className="animate-spin text-accent" />
                            ) : (
                              <RefreshCw size={14} strokeWidth={2} />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                    {abierta && (
                      <tr>
                        <td colSpan={5} className="bg-slate-50/70 px-4 py-3">
                          {!lista.length ? (
                            <p className="text-xs text-slate-500">
                              {e.actualizado_en
                                ? "SUNAT no muestra valores pendientes para esta empresa entre enero 2020 y el mes pasado."
                                : "Todavia no se leyeron las deudas de esta empresa."}
                            </p>
                          ) : (
                            <table className="w-full border-collapse text-xs">
                              <thead>
                                <tr className="text-left font-semibold uppercase tracking-wide text-slate-500">
                                  <th className="py-1.5 pr-3">Nro. valor</th>
                                  <th className="py-1.5 pr-3">Tipo</th>
                                  <th className="py-1.5 pr-3">Periodo</th>
                                  <th className="py-1.5 pr-3">Tributo</th>
                                  <th className="py-1.5 pr-3">Emision</th>
                                  <th className="py-1.5 pr-3">Notificacion</th>
                                  <th className="py-1.5 pr-3">Etapa</th>
                                  <th className="py-1.5 pr-3 text-right" title="Tributo que falta pagar, sin intereses">Tributo</th>
                                  <th className="py-1.5 pr-3 text-right">Interes</th>
                                  <th className="py-1.5 pr-3 text-right">Saldo</th>
                                  <th className="py-1.5">Situacion</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-slate-200/70">
                                {lista.map((v) => (
                                  <tr
                                    key={v.num_valor}
                                    className={`${v.vigente ? "text-ink" : "text-slate-400"} ${
                                      resaltados.includes(v.num_valor) ? "bg-amber-100/70 font-semibold" : ""
                                    }`}
                                    title={textoHistorial(v)}
                                  >
                                    <td className="py-1.5 pr-3 font-mono">
                                      {v.num_valor}
                                      {resaltados.includes(v.num_valor) && (
                                        <span className="ml-1.5 rounded-full bg-amber-500 px-1.5 py-0.5 font-sans text-[10px] font-bold uppercase text-white">
                                          Nuevo
                                        </span>
                                      )}
                                    </td>
                                    <td className="py-1.5 pr-3" title={v.tipo_descripcion}>{v.tipo_descripcion || v.tipo}</td>
                                    <td className="py-1.5 pr-3">{v.periodo}</td>
                                    <td className="max-w-[220px] truncate py-1.5 pr-3" title={`${v.cod_tributo} ${v.tributo}`}>
                                      {v.cod_tributo} · {v.tributo}
                                    </td>
                                    <td className="py-1.5 pr-3">{fechaIso(v.fecha_emision)}</td>
                                    <td className="py-1.5 pr-3">{fechaIso(v.fecha_notificacion)}</td>
                                    <td className="py-1.5 pr-3">
                                      {v.en_cobranza_coactiva ? (
                                        <span
                                          className="inline-flex items-center gap-1 rounded-full bg-red-50 px-1.5 py-0.5 font-bold text-red-700"
                                          title={v.num_expediente_coactivo ? `Expediente coactivo ${v.num_expediente_coactivo}` : undefined}
                                        >
                                          <Gavel size={11} strokeWidth={2} />
                                          {v.etapa || "Cobranza coactiva"}
                                        </span>
                                      ) : (
                                        v.etapa || "—"
                                      )}
                                      {v.num_expediente_coactivo && (
                                        <span className="block text-[10px] text-slate-500">Exp. {v.num_expediente_coactivo}</span>
                                      )}
                                    </td>
                                    <td
                                      className="py-1.5 pr-3 text-right"
                                      title={
                                        v.tributo_pendiente !== v.monto_tributo
                                          ? `Importe original ${soles.format(v.monto_tributo)} (tuvo pagos parciales)`
                                          : undefined
                                      }
                                    >
                                      {soles.format(v.tributo_pendiente)}
                                    </td>
                                    <td className="py-1.5 pr-3 text-right">{soles.format(v.interes)}</td>
                                    <td className="py-1.5 pr-3 text-right font-bold">{soles.format(v.saldo_total)}</td>
                                    <td className="py-1.5">
                                      {v.vigente ? (
                                        <span className="text-slate-600">Vigente · desde {fechaHora(v.detectado_en)}</span>
                                      ) : (
                                        <span>Ya no aparece desde {fechaHora(v.ya_no_aparece_desde)}</span>
                                      )}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <p className="mt-3 text-xs text-slate-500">
        Haz clic en una empresa para ver el detalle de sus valores. Pasa el cursor sobre un valor para ver su historial
        (cuando aparecio, cambios de etapa o de saldo). SUNAT no incluye en esta consulta los valores de fraccionamientos
        generales, anticipos de renta ni regalias mineras.
      </p>
    </>
  );
}
