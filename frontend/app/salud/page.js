"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  HeartPulse,
  RadioTower,
  RefreshCw,
  Clock,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Loader2,
  FileText,
  X,
} from "lucide-react";
import Sidebar from "../../components/Sidebar";
import { api, getToken } from "../../lib/api";

const OPCIONES_PERIODO = [
  { horas: 24, label: "24 horas" },
  { horas: 24 * 7, label: "7 dias" },
  { horas: 24 * 30, label: "30 dias" },
];

export default function SaludPage() {
  const router = useRouter();
  const [salud, setSalud] = useState(null);
  const [errores, setErrores] = useState([]);
  const [documentos, setDocumentos] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [horasAtras, setHorasAtras] = useState(24 * 7);
  const [ejecutando, setEjecutando] = useState(false);
  const [mensajeCanario, setMensajeCanario] = useState("");
  const [pdfVisto, setPdfVisto] = useState(null); // { empresaId, mensajeId, titulo } | null

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [horasAtras]);

  async function cargar() {
    setCargando(true);
    setError("");
    try {
      const [datosSalud, datosErrores, datosDocumentos] = await Promise.all([
        api.obtenerSalud(horasAtras),
        api.obtenerErroresRecientes(20),
        api.obtenerDocumentosRecientes(10),
      ]);
      setSalud(datosSalud);
      setErrores(datosErrores);
      setDocumentos(datosDocumentos);
    } catch (err) {
      setError(err.message);
    } finally {
      setCargando(false);
    }
  }

  async function ejecutarAhora() {
    setEjecutando(true);
    setMensajeCanario("");
    try {
      const resultado = await api.ejecutarCanario();
      if (resultado.chequeos_ejecutados === 0) {
        setMensajeCanario(
          resultado.motivo === "sin_empresa_canario"
            ? "No hay ninguna empresa marcada como cuenta canario. Marca una desde su pagina de detalle."
            : "El chequeo no encontro empresas validas para correr."
        );
      } else {
        setMensajeCanario(`Chequeo corrido: ${resultado.chequeos_ejecutados} empresa(s) verificada(s).`);
      }
      await cargar();
    } catch (err) {
      setMensajeCanario(err.message);
    } finally {
      setEjecutando(false);
    }
  }

  const canario = salud?.canario;
  const consultas = salud?.consultas;
  const tasaExitoCanarioGlobal =
    canario && canario.por_flujo.length > 0
      ? canario.por_flujo.reduce((acc, f) => acc + f.exitosos, 0) /
        canario.por_flujo.reduce((acc, f) => acc + f.total, 0)
      : null;

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 py-8 xl:px-12">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-ink">Salud del sistema</h1>
            <p className="mt-1 text-sm text-slate-600">
              Monitoreo del scraper (Fase 3): enterarse de un cambio en el portal de SUNAT por aqui, no por el
              reclamo de un cliente.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-slate-200 bg-white p-1">
              {OPCIONES_PERIODO.map((op) => (
                <button
                  key={op.horas}
                  onClick={() => setHorasAtras(op.horas)}
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-colors duration-300 ease-out ${
                    horasAtras === op.horas ? "bg-accent text-white" : "text-slate-500 hover:text-ink"
                  }`}
                >
                  {op.label}
                </button>
              ))}
            </div>
            <button
              onClick={ejecutarAhora}
              disabled={ejecutando}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-semibold text-slate-600 shadow-sm transition-all duration-300 ease-out hover:-translate-y-0.5 hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {ejecutando ? (
                <Loader2 size={15} strokeWidth={1.5} className="animate-spin" />
              ) : (
                <RefreshCw size={15} strokeWidth={1.5} />
              )}
              Ejecutar chequeo canario ahora
            </button>
          </div>
        </div>

        {mensajeCanario && (
          <div className="mt-4 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-600">
            {mensajeCanario}
          </div>
        )}

        {error && (
          <div className="mt-6 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
        )}

        {cargando || !salud ? (
          <p className="mt-8 text-sm text-slate-500">Cargando...</p>
        ) : (
          <>
            {canario.en_alerta && (
              <div className="mt-6 flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 p-5 animate-fade-in-up">
                <AlertTriangle size={20} strokeWidth={1.5} className="mt-0.5 shrink-0 text-red-600" />
                <div>
                  <h2 className="text-sm font-bold text-red-700">El chequeo canario esta fallando</h2>
                  <p className="mt-1 text-sm text-red-600/90">
                    Varios chequeos seguidos no lograron iniciar sesion en SUNAT. Esto suele significar que SUNAT
                    cambio algo en su portal -- revisa el playbook de fallos (PLAYBOOK_FALLOS_SUNAT.md) para los
                    primeros pasos de diagnostico.
                  </p>
                </div>
              </div>
            )}

            {!canario.tiene_empresa_canario && (
              <div className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800 animate-fade-in-up">
                Todavia no hay ninguna empresa marcada como cuenta canario, asi que este monitoreo dedicado esta
                inactivo. Marca una empresa de prueba desde su pagina de detalle para activarlo.
              </div>
            )}

            <div className="mt-7 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <TarjetaMetrica
                icono={RadioTower}
                etiqueta="Canario -- tasa de exito"
                valor={tasaExitoCanarioGlobal !== null ? `${Math.round(tasaExitoCanarioGlobal * 100)}%` : "--"}
                detalle={`${canario.total_checks} chequeo(s) en el periodo`}
              />
              <TarjetaMetrica
                icono={canario.ultimo_resultado === false ? XCircle : CheckCircle2}
                iconoColor={canario.ultimo_resultado === false ? "text-red-500" : "text-emerald-500"}
                etiqueta="Ultimo chequeo canario"
                valor={
                  canario.ultimo_resultado === null
                    ? "Sin datos"
                    : canario.ultimo_resultado
                    ? "Exitoso"
                    : "Fallo"
                }
                detalle={canario.ultimo_check_en ? new Date(canario.ultimo_check_en).toLocaleString() : "-"}
              />
              <TarjetaMetrica
                icono={HeartPulse}
                etiqueta="Consultas normales -- tasa de exito"
                valor={consultas.tasa_exito !== null ? `${Math.round(consultas.tasa_exito * 100)}%` : "--"}
                detalle={`${consultas.exitosas} exitosa(s) / ${consultas.fallidas} con error`}
              />
              <TarjetaMetrica
                icono={Clock}
                etiqueta="Duracion promedio (consultas)"
                valor={consultas.duracion_prom_seg !== null ? `${consultas.duracion_prom_seg}s` : "--"}
                detalle={`${consultas.total} consulta(s) en el periodo`}
              />
            </div>

            <div className="mt-10 grid grid-cols-1 gap-8 xl:grid-cols-2">
              <SeccionPorFlujo porFlujo={canario.por_flujo} />
              <SeccionErroresRecientes errores={errores} />
            </div>

            <div className="mt-10">
              <SeccionDocumentosRecientes
                documentos={documentos}
                onVerPdf={(d) => setPdfVisto({ empresaId: d.empresa_id, mensajeId: d.mensaje_id, titulo: d.asunto })}
              />
            </div>
          </>
        )}
      </main>

      {pdfVisto && <ModalPdfSalud info={pdfVisto} onClose={() => setPdfVisto(null)} />}
    </div>
  );
}

function TarjetaMetrica({ icono: Icono, iconoColor, etiqueta, valor, detalle }) {
  return (
    <div className="surface-card animate-fade-in-up p-5">
      <div className={`flex items-center gap-2 text-slate-500`}>
        <Icono size={14} strokeWidth={1.5} className={iconoColor} />
        <span className="text-xs font-medium uppercase tracking-wide">{etiqueta}</span>
      </div>
      <div className="mt-2 text-3xl font-bold tracking-tight text-ink">{valor}</div>
      <p className="mt-0.5 text-xs text-slate-400">{detalle}</p>
    </div>
  );
}

function SeccionPorFlujo({ porFlujo }) {
  return (
    <section>
      <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">
        Canario por tipo de flujo detectado
      </h2>
      <p className="mt-1 text-xs text-slate-400">
        Un cambio en esta distribucion a lo largo del tiempo es una senal temprana de que SUNAT esta modificando su
        portal.
      </p>

      {porFlujo.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">Todavia no hay chequeos canario en este periodo.</p>
      ) : (
        <div className="surface-card mt-3 divide-y divide-slate-100 overflow-hidden">
          {porFlujo.map((f) => (
            <div key={f.flujo} className="flex items-center justify-between px-5 py-3.5">
              <div>
                <div className="text-sm font-medium text-ink">{f.flujo}</div>
                <div className="text-xs text-slate-500">
                  {f.exitosos} / {f.total} exitoso(s)
                  {f.duracion_prom_seg !== null ? ` · ${f.duracion_prom_seg}s promedio` : ""}
                </div>
              </div>
              <span
                className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                  f.tasa_exito >= 0.9
                    ? "bg-emerald-50 text-emerald-600"
                    : f.tasa_exito >= 0.5
                    ? "bg-amber-50 text-amber-600"
                    : "bg-red-50 text-red-600"
                }`}
              >
                {Math.round(f.tasa_exito * 100)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function SeccionErroresRecientes({ errores }) {
  return (
    <section>
      <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">Errores recientes</h2>
      <p className="mt-1 text-xs text-slate-400">
        Mezclando canario y consultas normales, mas recientes primero -- ver si el problema es de un solo tipo o de
        ambos.
      </p>

      {errores.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">Sin errores recientes. Todo funcionando.</p>
      ) : (
        <div className="surface-card mt-3 divide-y divide-slate-100 overflow-hidden">
          {errores.map((e, i) => (
            <div key={i} className="flex items-start gap-3 px-5 py-3.5">
              <XCircle size={16} strokeWidth={1.5} className="mt-0.5 shrink-0 text-red-500" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-ink">
                    {e.empresa_razon_social || "?"} ({e.empresa_ruc || "?"})
                  </span>
                  <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold uppercase text-slate-500">
                    {e.tipo}
                  </span>
                </div>
                <div className="mt-0.5 truncate text-xs text-slate-500" title={e.error || ""}>
                  {e.error || "Error desconocido"}
                </div>
                <div className="mt-0.5 text-xs text-slate-400">
                  {e.ocurrido_en ? new Date(e.ocurrido_en).toLocaleString() : "-"}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function SeccionDocumentosRecientes({ documentos, onVerPdf }) {
  return (
    <section>
      <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">Documentos recientes</h2>
      <p className="mt-1 text-xs text-slate-400">
        Los ultimos 10 PDFs descargados, de cualquier empresa -- para confirmar de un vistazo que la descarga de
        documentos sigue funcionando.
      </p>

      {documentos.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">Todavia no se descargo ningun documento.</p>
      ) : (
        <div className="surface-card mt-3 divide-y divide-slate-100 overflow-hidden">
          {documentos.map((d) => (
            <button
              key={d.mensaje_id}
              onClick={() => onVerPdf(d)}
              className="flex w-full items-center gap-3 px-5 py-3.5 text-left transition-colors duration-300 ease-out hover:bg-slate-50"
            >
              <FileText size={16} strokeWidth={1.5} className="shrink-0 text-slate-400" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium text-ink">
                    {d.empresa_razon_social} ({d.empresa_ruc})
                  </span>
                  {d.tipo && (
                    <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold uppercase text-slate-500">
                      {d.tipo}
                    </span>
                  )}
                </div>
                <div className="mt-0.5 truncate text-xs text-slate-500" title={d.asunto}>
                  {d.asunto}
                </div>
              </div>
              <span className="shrink-0 text-xs text-slate-400">
                {d.descubierto_en ? new Date(d.descubierto_en).toLocaleString() : "-"}
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function ModalPdfSalud({ info, onClose }) {
  const [url, setUrl] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelado = false;
    setCargando(true);
    setError("");
    api
      .obtenerDocumentoUrl(info.empresaId, info.mensajeId)
      .then((u) => {
        if (!cancelado) setUrl(u);
      })
      .catch((err) => {
        if (!cancelado) setError(err.message);
      })
      .finally(() => {
        if (!cancelado) setCargando(false);
      });
    return () => {
      cancelado = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [info.mensajeId]);

  function cerrar() {
    if (url) URL.revokeObjectURL(url);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-6" onClick={cerrar}>
      <div
        className="flex h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-soft-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <span className="truncate text-sm font-semibold text-ink">{info.titulo}</span>
          <button
            onClick={cerrar}
            className="flex items-center justify-center rounded-lg p-1.5 text-slate-500 transition-colors duration-300 ease-out hover:bg-slate-100 hover:text-ink"
            aria-label="Cerrar"
          >
            <X size={18} strokeWidth={1.5} />
          </button>
        </div>
        {cargando ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-slate-400">
            <Loader2 size={24} strokeWidth={1.5} className="animate-spin" />
            <p className="text-sm">Cargando documento...</p>
          </div>
        ) : error ? (
          <div className="flex h-full items-center justify-center p-8 text-center text-sm text-red-600">{error}</div>
        ) : (
          <iframe src={url} title={info.titulo} className="flex-1 border-0" />
        )}
      </div>
    </div>
  );
}
