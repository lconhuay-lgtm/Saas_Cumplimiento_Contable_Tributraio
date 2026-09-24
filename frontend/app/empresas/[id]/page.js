"use client";
import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, CheckCheck, Mail, MailOpen, FileText, Loader2, Inbox, Filter, X, RadioTower, Award, ListChecks, Plus, Trash2, UserCog, ClipboardPlus, ClipboardCheck, KeyRound } from "lucide-react";
import Sidebar from "../../../components/Sidebar";
import { api, getToken } from "../../../lib/api";
import { colorPuntoTipo } from "../../../lib/tiposMensaje";

const ETIQUETAS_FILTRO_ESPECIAL = {
  pendientes: "mensajes pendientes",
  hoy: "novedades de hoy",
};

export default function DetalleEmpresaPage() {
  const { id } = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [empresa, setEmpresa] = useState(null);
  const [mensajes, setMensajes] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [filtroTipo, setFiltroTipo] = useState("Todos");
  // Llega desde las tarjetas/dashboard con ?filtro=pendientes|hoy para entrar
  // directo con ese recorte aplicado, ademas de las pestanas por tipo.
  const [filtroEspecial, setFiltroEspecial] = useState(searchParams.get("filtro"));
  const [seleccionado, setSeleccionado] = useState(null); // mensaje completo
  const [pdfUrl, setPdfUrl] = useState(null);
  const [cargandoPdf, setCargandoPdf] = useState(false);
  const [errorPdf, setErrorPdf] = useState("");
  // Cartera: usuarios del tenant, para el selector "Asignado a" (editable
  // solo por un admin -- un miembro solo la ve como dato, ver acceso.py).
  const [usuarios, setUsuarios] = useState([]);
  const [usuarioActual, setUsuarioActual] = useState(null);
  // Notificacion -> tarea: mensaje_id -> tarea, para saber cuales ya tienen
  // una creada (boton "Crear tarea" se vuelve "Ver tarea").
  const [tareasPorMensaje, setTareasPorMensaje] = useState({});
  const [mensajeParaTarea, setMensajeParaTarea] = useState(null); // mensaje completo | null
  const [mostrarEditarCredenciales, setMostrarEditarCredenciales] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    cargar();
    api.me().then(setUsuarioActual).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Limpiar la blob URL anterior cada vez que se selecciona un mensaje
  // distinto o se sale de la pagina, para no acumular memoria.
  useEffect(() => {
    return () => {
      if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdfUrl]);

  async function cargar() {
    setCargando(true);
    setError("");
    try {
      const [datosEmpresa, datosMensajes, datosUsuarios, datosTareas] = await Promise.all([
        api.obtenerEmpresa(id),
        api.listarMensajes(id),
        api.listarUsuarios().catch(() => []),
        api.listarTareas({ empresaId: id }).catch(() => []),
      ]);
      setEmpresa(datosEmpresa);
      setMensajes(datosMensajes);
      setUsuarios(datosUsuarios);
      const porMensaje = {};
      for (const t of datosTareas) {
        if (t.mensaje_buzon_id) porMensaje[t.mensaje_buzon_id] = t;
      }
      setTareasPorMensaje(porMensaje);
    } catch (err) {
      setError(err.message);
    } finally {
      setCargando(false);
    }
  }

  async function cambiarAsignado(usuarioId) {
    try {
      await api.actualizarEmpresa(id, { activo: empresa.activo, asignado_a_usuario_id: usuarioId || null });
      cargar();
    } catch (err) {
      alert(err.message);
    }
  }

  async function toggleLeido(mensaje) {
    try {
      await api.marcarLeido(id, mensaje.id, !mensaje.leido);
      cargar();
    } catch (err) {
      alert(err.message);
    }
  }

  async function marcarTodos() {
    try {
      const resultado = await api.marcarTodosLeidos(id);
      if (resultado.actualizados === 0) {
        alert("No habia mensajes pendientes.");
      }
      cargar();
    } catch (err) {
      alert(err.message);
    }
  }

  // Fase 3 (confiabilidad/observabilidad): marca/desmarca esta empresa como
  // la "cuenta controlada" que usa el chequeo canario (ver Salud del
  // sistema) -- un login de prueba periodico, separado de las consultas
  // normales, para enterarse de un cambio en el portal de SUNAT antes de
  // que un cliente lo reporte.
  async function toggleCanario() {
    try {
      await api.actualizarEmpresa(id, { activo: empresa.activo, es_canario: !empresa.es_canario });
      cargar();
    } catch (err) {
      alert(err.message);
    }
  }

  // Modulo de cronograma SUNAT: si esta empresa usa la fecha extendida de
  // "Buenos Contribuyentes y UESP" en vez del cronograma general por
  // ultimo digito de RUC (ver backend/app/cronograma_sunat.py).
  async function toggleBuenContribuyente() {
    try {
      await api.actualizarEmpresa(id, {
        activo: empresa.activo,
        es_buen_contribuyente: !empresa.es_buen_contribuyente,
      });
      cargar();
    } catch (err) {
      alert(err.message);
    }
  }

  async function eliminarEmpresa() {
    if (!confirm(`Eliminar "${empresa.razon_social}"? Se borra tambien su historial de mensajes, tareas y credenciales guardadas. Esto no se puede deshacer.`)) {
      return;
    }
    try {
      await api.eliminarEmpresa(id);
      router.push("/empresas");
    } catch (err) {
      alert(err.message);
    }
  }

  async function verPdf(mensaje) {
    setSeleccionado(mensaje);
    setErrorPdf("");
    setPdfUrl(null);
    setCargandoPdf(true);
    try {
      const url = await api.obtenerDocumentoUrl(id, mensaje.id);
      setPdfUrl(url);
    } catch (err) {
      setErrorPdf(err.message);
    } finally {
      setCargandoPdf(false);
    }
  }

  const hayPendientes = mensajes.some((m) => !m.leido);

  // Pestanas dinamicas: solo los tipos que de verdad aparecen en los
  // mensajes de esta empresa, ordenadas por cuantas hay (las mas
  // frecuentes primero) para que las pestanas utiles queden a la vista sin
  // tener que hacer scroll horizontal.
  const pestanas = useMemo(() => {
    const conteo = {};
    for (const m of mensajes) {
      const tipo = m.tipo || "Otros";
      conteo[tipo] = (conteo[tipo] || 0) + 1;
    }
    const ordenadas = Object.entries(conteo).sort((a, b) => b[1] - a[1]);
    return [["Todos", mensajes.length], ...ordenadas];
  }, [mensajes]);

  const inicioDeHoy = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d;
  }, []);

  const mensajesFiltrados = mensajes
    .filter((m) => filtroTipo === "Todos" || (m.tipo || "Otros") === filtroTipo)
    .filter((m) => {
      if (filtroEspecial === "pendientes") return !m.leido;
      if (filtroEspecial === "hoy") return new Date(m.descubierto_en) >= inicioDeHoy;
      return true;
    });

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 py-8 xl:px-12">
        <Link
          href="/empresas"
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-semibold text-slate-600 shadow-sm transition-all duration-300 ease-out hover:-translate-y-0.5 hover:border-accent hover:text-accent"
        >
          <ArrowLeft size={15} strokeWidth={1.5} />
          Volver a empresas
        </Link>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-ink">
              {empresa ? empresa.razon_social : "Mensajes del buzon"}
            </h1>
            {empresa && (
              <p className="mt-0.5 text-sm text-slate-500">
                RUC {empresa.ruc} &middot; Mensajes del buzon
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {empresa && usuarioActual?.rol === "admin" && (
              <div
                className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm"
                title="Cartera: que usuario del estudio tiene asignada esta empresa (solo el admin puede reasignarla)"
              >
                <UserCog size={15} strokeWidth={1.5} className="shrink-0 text-slate-400" />
                <select
                  value={empresa.asignado_a_usuario_id || ""}
                  onChange={(e) => cambiarAsignado(e.target.value)}
                  className="bg-transparent text-sm font-medium text-slate-600 outline-none"
                >
                  <option value="">Sin asignar</option>
                  {usuarios.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.email}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {empresa && usuarioActual && usuarioActual.rol !== "admin" && (
              <div
                className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-500"
                title="Cartera: solo el admin puede reasignarla"
              >
                <UserCog size={15} strokeWidth={1.5} className="shrink-0 text-slate-400" />
                {usuarios.find((u) => u.id === empresa.asignado_a_usuario_id)?.email || "Sin asignar"}
              </div>
            )}
            {empresa && (
              <button
                onClick={toggleCanario}
                title="Fase 3: usar esta empresa como cuenta de prueba para el monitoreo automatico del login a SUNAT (ver Salud del sistema)"
                className={`flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-sm font-medium transition-all duration-300 ease-out ${
                  empresa.es_canario
                    ? "border-accent bg-accent-light text-accent"
                    : "border-slate-200 text-slate-500 hover:border-accent hover:text-accent"
                }`}
              >
                <RadioTower size={15} strokeWidth={1.5} />
                {empresa.es_canario ? "Cuenta canario activa" : "Marcar como cuenta canario"}
              </button>
            )}
            {empresa && (
              <button
                onClick={toggleBuenContribuyente}
                title="Modulo de cronograma: usar la fecha de vencimiento extendida de 'Buenos Contribuyentes y UESP' en vez del cronograma general por ultimo digito de RUC"
                className={`flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-sm font-medium transition-all duration-300 ease-out ${
                  empresa.es_buen_contribuyente
                    ? "border-accent bg-accent-light text-accent"
                    : "border-slate-200 text-slate-500 hover:border-accent hover:text-accent"
                }`}
              >
                <Award size={15} strokeWidth={1.5} />
                {empresa.es_buen_contribuyente ? "Buen Contribuyente" : "Marcar Buen Contribuyente"}
              </button>
            )}
            <button
              onClick={marcarTodos}
              disabled={!hayPendientes}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition-all duration-300 ease-out hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              <CheckCheck size={15} strokeWidth={1.5} />
              Marcar todos como leidos
            </button>
            {empresa && (
              <button
                onClick={() => setMostrarEditarCredenciales(true)}
                title="Cambiar el usuario/clave SOL guardados de esta empresa"
                className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3.5 py-2 text-sm font-medium text-slate-500 transition-all duration-300 ease-out hover:border-accent hover:text-accent"
              >
                <KeyRound size={15} strokeWidth={1.5} />
                Credenciales
              </button>
            )}
            {empresa && (
              <button
                onClick={eliminarEmpresa}
                title="Eliminar esta empresa y todo su historial"
                className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3.5 py-2 text-sm font-medium text-slate-500 transition-all duration-300 ease-out hover:border-red-300 hover:text-red-600"
              >
                <Trash2 size={15} strokeWidth={1.5} />
                Eliminar
              </button>
            )}
          </div>
        </div>

        {error && (
          <div className="mt-6 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
        )}

        {empresa && <SeccionObligaciones empresaId={id} />}

        {cargando ? (
          <p className="mt-8 text-sm text-slate-500">Cargando...</p>
        ) : mensajes.length === 0 ? (
          <p className="mt-8 text-sm text-slate-500">
            Todavia no hay mensajes guardados para esta empresa. Usa &quot;Consultar en vivo&quot; desde la lista de
            empresas.
          </p>
        ) : (
          <div className="mt-6 flex flex-col gap-6 xl:flex-row xl:items-start">
            {/* Panel izquierdo: pestanas por tipo + lista de mensajes */}
            <div className="min-w-0 xl:w-[34%] xl:shrink-0">
              {filtroEspecial && ETIQUETAS_FILTRO_ESPECIAL[filtroEspecial] && (
                <div className="mb-3 flex items-center gap-2 rounded-lg bg-accent-light px-3 py-2 text-xs font-medium text-accent">
                  <Filter size={12} strokeWidth={1.5} />
                  Mostrando solo: {ETIQUETAS_FILTRO_ESPECIAL[filtroEspecial]}
                  <button
                    onClick={() => setFiltroEspecial(null)}
                    className="ml-auto flex items-center gap-1 rounded-full px-1.5 py-0.5 hover:bg-white/50"
                  >
                    <X size={12} strokeWidth={1.5} />
                    Quitar
                  </button>
                </div>
              )}

              <div className="flex flex-wrap gap-1.5 border-b border-slate-100 pb-3">
                {pestanas.map(([tipo, cantidad]) => (
                  <button
                    key={tipo}
                    onClick={() => setFiltroTipo(tipo)}
                    className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors duration-300 ease-out ${
                      filtroTipo === tipo
                        ? "bg-accent text-white"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                    }`}
                  >
                    {tipo !== "Todos" && (
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${colorPuntoTipo(tipo)}`} />
                    )}
                    {tipo}
                    <span
                      className={`rounded-full px-1.5 text-[11px] ${
                        filtroTipo === tipo ? "bg-white/20" : "bg-white text-slate-500"
                      }`}
                    >
                      {cantidad}
                    </span>
                  </button>
                ))}
              </div>

              <div className="surface-card mt-4 max-h-[80vh] divide-y divide-slate-100 overflow-y-auto">
                {mensajesFiltrados.length === 0 ? (
                  <p className="p-5 text-sm text-slate-500">No hay mensajes en esta categoria/filtro.</p>
                ) : (
                  mensajesFiltrados.map((m) => (
                    <div
                      key={m.id}
                      onClick={() => m.tiene_documento && verPdf(m)}
                      className={`px-4 py-3.5 transition-colors duration-300 ease-out ${
                        m.tiene_documento ? "cursor-pointer" : ""
                      } ${seleccionado?.id === m.id ? "bg-accent-light" : m.leido ? "" : "bg-accent-light/30"} ${
                        m.tiene_documento ? "hover:bg-accent-light/60" : ""
                      }`}
                    >
                      <div className="flex items-start gap-2.5">
                        <span
                          className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${m.leido ? "bg-slate-200" : "bg-accent"}`}
                        />
                        <div className="min-w-0 flex-1">
                          <div className={`text-sm ${m.leido ? "text-slate-600" : "font-semibold text-ink"}`}>
                            {m.asunto}
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
                            <span>{new Date(m.fecha_publicacion).toLocaleDateString()}</span>
                            {m.tiene_documento && (
                              <span className="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-500">
                                <FileText size={11} strokeWidth={1.5} />
                                PDF
                              </span>
                            )}
                          </div>
                        </div>
                        {tareasPorMensaje[m.id] ? (
                          <Link
                            href="/tareas"
                            onClick={(e) => e.stopPropagation()}
                            title={`Ya tiene una tarea creada (${tareasPorMensaje[m.id].estado})`}
                            className="shrink-0 rounded-lg p-1.5 text-emerald-500 transition-colors duration-300 ease-out hover:bg-emerald-50"
                          >
                            <ClipboardCheck size={14} strokeWidth={1.5} />
                          </Link>
                        ) : (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setMensajeParaTarea(m);
                            }}
                            className="shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors duration-300 ease-out hover:bg-slate-100 hover:text-accent"
                            title="Crear tarea a partir de esta notificacion"
                            aria-label="Crear tarea"
                          >
                            <ClipboardPlus size={14} strokeWidth={1.5} />
                          </button>
                        )}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleLeido(m);
                          }}
                          className="shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors duration-300 ease-out hover:bg-slate-100 hover:text-accent"
                          title={m.leido ? "Marcar no leido" : "Marcar leido"}
                          aria-label={m.leido ? "Marcar no leido" : "Marcar leido"}
                        >
                          {m.leido ? <Mail size={14} strokeWidth={1.5} /> : <MailOpen size={14} strokeWidth={1.5} />}
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Panel derecho: visor de PDF, grande y fijo mientras se hace scroll a la lista */}
            <div className="min-w-0 flex-1 xl:sticky xl:top-6">
              <div className="surface-card flex h-[80vh] flex-col overflow-hidden xl:h-[calc(100vh-140px)]">
                {!seleccionado ? (
                  <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center text-slate-400">
                    <FileText size={32} strokeWidth={1.2} />
                    <p className="text-sm">Selecciona un mensaje con PDF para verlo aqui</p>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
                      <span className="truncate text-sm font-semibold text-ink" title={seleccionado.asunto}>
                        {seleccionado.asunto}
                      </span>
                    </div>
                    {cargandoPdf ? (
                      <div className="flex h-full flex-col items-center justify-center gap-2 text-slate-400">
                        <Loader2 size={24} strokeWidth={1.5} className="animate-spin" />
                        <p className="text-sm">Cargando documento...</p>
                      </div>
                    ) : errorPdf ? (
                      <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
                        <Inbox size={28} strokeWidth={1.2} className="text-slate-300" />
                        <p className="text-sm text-red-600">{errorPdf}</p>
                      </div>
                    ) : (
                      <iframe src={pdfUrl} title={seleccionado.asunto} className="flex-1 border-0" />
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        )}

        {mensajeParaTarea && (
          <ModalCrearTarea
            empresaId={id}
            mensaje={mensajeParaTarea}
            onCerrar={() => setMensajeParaTarea(null)}
            onCreada={() => {
              setMensajeParaTarea(null);
              cargar();
            }}
          />
        )}

        {mostrarEditarCredenciales && (
          <ModalEditarCredenciales
            empresaId={id}
            onCerrar={() => setMostrarEditarCredenciales(false)}
            onGuardado={() => {
              setMostrarEditarCredenciales(false);
              cargar();
            }}
          />
        )}
      </main>
    </div>
  );
}

function ModalEditarCredenciales({ empresaId, onCerrar, onGuardado }) {
  const [usuarioSol, setUsuarioSol] = useState("");
  const [claveSol, setClaveSol] = useState("");
  const [claveSolRepetir, setClaveSolRepetir] = useState("");
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    if (claveSol !== claveSolRepetir) {
      setError("La clave SOL y su repeticion no coinciden.");
      return;
    }
    setGuardando(true);
    try {
      await api.actualizarCredencialesEmpresa(empresaId, usuarioSol, claveSol);
      onGuardado();
    } catch (err) {
      setError(err.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
      <div className="surface-card w-full max-w-sm p-6">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-ink">Cambiar usuario/clave SOL</h3>
          <button onClick={onCerrar} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-ink" aria-label="Cerrar">
            <X size={16} strokeWidth={1.5} />
          </button>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          Reemplaza por completo lo guardado -- usalo cuando el cliente cambio su clave en SUNAT.
        </p>

        {error && (
          <div className="mt-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-600">{error}</div>
        )}

        <form onSubmit={onSubmit} className="mt-4 space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Usuario SOL</label>
            <input value={usuarioSol} onChange={(e) => setUsuarioSol(e.target.value)} required className="campo-input" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Clave SOL</label>
            <input type="password" value={claveSol} onChange={(e) => setClaveSol(e.target.value)} required className="campo-input" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Repetir clave SOL</label>
            <input type="password" value={claveSolRepetir} onChange={(e) => setClaveSolRepetir(e.target.value)} required className="campo-input" />
          </div>
          <button
            type="submit"
            disabled={guardando}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent py-2.5 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
          >
            {guardando && <Loader2 size={15} strokeWidth={2} className="animate-spin" />}
            {guardando ? "Guardando..." : "Guardar credenciales"}
          </button>
        </form>
      </div>
    </div>
  );
}

// Notificacion -> tarea: se le pide al usuario la fecha real (si el
// documento la trae), en vez de que el sistema invente un plazo legal --
// ver la decision tomada para esta funcionalidad en el analisis del
// producto. La tarea queda vinculada al mensaje via mensaje_buzon_id y
// alimenta tanto /tareas como el calendario de /cronograma.
function ModalCrearTarea({ empresaId, mensaje, onCerrar, onCreada }) {
  const [titulo, setTitulo] = useState(mensaje.asunto);
  const [fechaVencimiento, setFechaVencimiento] = useState("");
  const [prioridad, setPrioridad] = useState("media");
  const [observaciones, setObservaciones] = useState("");
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setGuardando(true);
    try {
      await api.crearTareaManual({
        empresa_id: empresaId,
        mensaje_buzon_id: mensaje.id,
        titulo,
        tipo: "notificacion",
        fecha_vencimiento: fechaVencimiento ? new Date(fechaVencimiento).toISOString() : null,
        prioridad,
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
      <div className="surface-card w-full max-w-md p-6">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-ink">Crear tarea desde esta notificacion</h3>
          <button
            onClick={onCerrar}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-ink"
            aria-label="Cerrar"
          >
            <X size={16} strokeWidth={1.5} />
          </button>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-600">{error}</div>
        )}

        <form onSubmit={onSubmit} className="mt-4 space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Titulo</label>
            <input value={titulo} onChange={(e) => setTitulo(e.target.value)} required className="campo-input" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
                Fecha de vencimiento
              </label>
              <input
                type="date"
                value={fechaVencimiento}
                onChange={(e) => setFechaVencimiento(e.target.value)}
                className="campo-input"
              />
              <p className="mt-1 text-[11px] text-slate-400">
                Opcional -- solo si el documento trae un plazo explicito.
              </p>
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
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
              Observaciones
            </label>
            <textarea
              value={observaciones}
              onChange={(e) => setObservaciones(e.target.value)}
              rows={3}
              className="campo-input"
            />
          </div>
          <button
            type="submit"
            disabled={guardando}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent py-2.5 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
          >
            {guardando && <Loader2 size={15} strokeWidth={2} className="animate-spin" />}
            {guardando ? "Creando..." : "Crear tarea"}
          </button>
        </form>
      </div>
    </div>
  );
}

const ETIQUETAS_TIPO_OBLIGACION = {
  planilla: "Planilla",
  afp: "AFP",
  sbs: "Reporte SBS",
  otro: "Otro",
};

const ETIQUETAS_REGLA = {
  cronograma_sunat: "Sigue el cronograma SUNAT (misma fecha que Planilla/PLAME)",
  dia_fijo_mes: "Vence un dia fijo cada mes",
  manual: "Sin regla automatica -- se carga la fecha a mano cada vez",
};

// Modulo de Tareas/Agenda: que obligaciones RECURRENTES tiene esta empresa
// ademas del cronograma general (que aplica solo con estar activa). No
// todas las empresas tienen planilla, ni todas son AFP, ni todas reportan
// a la SBS -- esta seccion es donde se configura cual le toca a cada una.
function SeccionObligaciones({ empresaId }) {
  const [obligaciones, setObligaciones] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [mostrarForm, setMostrarForm] = useState(false);

  useEffect(() => {
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empresaId]);

  async function cargar() {
    setCargando(true);
    try {
      const data = await api.listarObligaciones(empresaId);
      setObligaciones(data);
    } catch (err) {
      // silencioso -- no es critico para el resto de la pagina
    } finally {
      setCargando(false);
    }
  }

  async function toggleActiva(ob) {
    try {
      await api.actualizarObligacion(ob.id, { activa: !ob.activa });
      cargar();
    } catch (err) {
      alert(err.message);
    }
  }

  async function eliminar(ob) {
    if (!confirm(`Eliminar la obligacion "${ob.nombre}"? Las tareas ya generadas no se borran.`)) return;
    try {
      await api.eliminarObligacion(ob.id);
      cargar();
    } catch (err) {
      alert(err.message);
    }
  }

  return (
    <div className="surface-card mt-6 p-5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 text-sm font-bold uppercase tracking-wide text-slate-500">
          <ListChecks size={14} strokeWidth={1.75} className="text-slate-400" />
          Obligaciones de esta empresa
        </h2>
        <button
          onClick={() => setMostrarForm((v) => !v)}
          className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 transition-all duration-300 ease-out hover:border-accent hover:text-accent"
        >
          {mostrarForm ? <X size={13} strokeWidth={1.5} /> : <Plus size={13} strokeWidth={1.5} />}
          {mostrarForm ? "Cancelar" : "Agregar"}
        </button>
      </div>

      {cargando ? (
        <p className="mt-3 text-sm text-slate-500">Cargando...</p>
      ) : obligaciones.length === 0 && !mostrarForm ? (
        <p className="mt-3 text-sm text-slate-500">
          Sin obligaciones extra configuradas -- solo el cronograma general (IGV-Renta/PLAME).
        </p>
      ) : (
        <div className="mt-3 space-y-2">
          {obligaciones.map((ob) => (
            <div
              key={ob.id}
              className={`flex items-center justify-between gap-3 rounded-lg border px-3.5 py-2.5 ${
                ob.activa ? "border-slate-200" : "border-slate-100 bg-slate-50/60 opacity-60"
              }`}
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="rounded-full bg-accent-light px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-accent">
                    {ETIQUETAS_TIPO_OBLIGACION[ob.tipo] || ob.tipo}
                  </span>
                  <span className="text-sm font-medium text-ink">{ob.nombre}</span>
                </div>
                <p className="mt-0.5 text-xs text-slate-500">
                  {ETIQUETAS_REGLA[ob.regla_vencimiento]}
                  {ob.regla_vencimiento === "dia_fijo_mes" && ob.dia_fijo ? ` (dia ${ob.dia_fijo})` : ""}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  onClick={() => toggleActiva(ob)}
                  className="rounded-lg px-2 py-1 text-[11px] font-semibold text-slate-500 hover:bg-slate-100"
                >
                  {ob.activa ? "Desactivar" : "Activar"}
                </button>
                <button
                  onClick={() => eliminar(ob)}
                  className="flex items-center justify-center rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
                  aria-label="Eliminar"
                >
                  <Trash2 size={14} strokeWidth={1.5} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {mostrarForm && (
        <FormularioObligacion
          empresaId={empresaId}
          onCreada={() => {
            setMostrarForm(false);
            cargar();
          }}
        />
      )}
    </div>
  );
}

function FormularioObligacion({ empresaId, onCreada }) {
  const [tipo, setTipo] = useState("planilla");
  const [nombre, setNombre] = useState("Planilla mensual");
  const [reglaVencimiento, setReglaVencimiento] = useState("cronograma_sunat");
  const [diaFijo, setDiaFijo] = useState(5);
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setGuardando(true);
    try {
      await api.crearObligacion(empresaId, {
        tipo,
        nombre,
        regla_vencimiento: reglaVencimiento,
        dia_fijo: reglaVencimiento === "dia_fijo_mes" ? Number(diaFijo) : null,
      });
      onCreada();
    } catch (err) {
      setError(err.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="mt-4 rounded-lg border border-dashed border-slate-300 p-4">
      {error && (
        <div className="mb-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-600">{error}</div>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Tipo</label>
          <select value={tipo} onChange={(e) => setTipo(e.target.value)} className="campo-input">
            <option value="planilla">Planilla</option>
            <option value="afp">AFP</option>
            <option value="sbs">Reporte SBS</option>
            <option value="otro">Otro</option>
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Nombre</label>
          <input value={nombre} onChange={(e) => setNombre(e.target.value)} required className="campo-input" />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Regla de vencimiento</label>
          <select value={reglaVencimiento} onChange={(e) => setReglaVencimiento(e.target.value)} className="campo-input">
            <option value="cronograma_sunat">Cronograma SUNAT (Planilla/AFP via PLAME)</option>
            <option value="dia_fijo_mes">Dia fijo del mes</option>
            <option value="manual">Manual (SBS, sin regla fija)</option>
          </select>
        </div>
        {reglaVencimiento === "dia_fijo_mes" && (
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Dia del mes</label>
            <input
              type="number"
              min={1}
              max={31}
              value={diaFijo}
              onChange={(e) => setDiaFijo(e.target.value)}
              className="campo-input"
            />
          </div>
        )}
      </div>
      <button
        type="submit"
        disabled={guardando}
        className="mt-3 flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-xs font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
      >
        {guardando && <Loader2 size={13} strokeWidth={1.5} className="animate-spin" />}
        {guardando ? "Guardando..." : "Agregar obligacion"}
      </button>
    </form>
  );
}
