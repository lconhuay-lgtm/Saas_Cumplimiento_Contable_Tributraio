"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  Plus,
  Upload,
  RefreshCw,
  Loader2,
  X,
  FileSpreadsheet,
  Inbox,
  Mail,
  Zap,
  Search,
  Sparkles,
  FileText,
  ArrowRight,
  ExternalLink,
  AlertTriangle,
  IdCard,
  LogIn,
  CheckCheck,
} from "lucide-react";
import Sidebar from "../../components/Sidebar";
import { api, getToken, API_URL } from "../../lib/api";
import { colorBadgeTipo } from "../../lib/tiposMensaje";

// Menu SOL generico -- YA NO es el boton principal de "Op. en Linea" (eso
// ahora hace login automatico, ver entrarDirectoASunat), pero se deja como
// enlace de respaldo (icono chiquito en la esquina de la tarjeta) por si el
// ingreso automatico falla o SUNAT pide algo que el autoenvio no puede
// resolver solo (por ejemplo un captcha). Probado: si el usuario ya tiene
// una sesion abierta en SUNAT en ESE MISMO navegador, entra directo sin
// volver a loguearse (cookie de sesion normal, no un token en la URL -- los
// "*" son literales). Si no tiene sesion abierta, SUNAT pide usuario/clave
// como siempre. Nunca pasamos ninguna credencial por esta URL.
const URL_SUNAT_MENU = "https://e-menu.sunat.gob.pe/cl-ti-itmenu/MenuInternet.htm?pestana=*&agrupacion=*";

// "Consultar todas" espacia cada empresa ~45s de la siguiente para no
// parecer trafico sospechoso ante SUNAT -- con varias decenas de empresas
// eso ya son horas, no "unos minutos". Mostrar la estimacion real evita
// que el boton parezca colgado cuando en realidad esta avanzando bien,
// solo que despacio por diseño.
function formatoDuracionEstimada(cantidadEmpresas, espaciadoSeg = 45) {
  const totalMin = Math.ceil((cantidadEmpresas * espaciadoSeg) / 60);
  if (totalMin < 60) return `~${totalMin} minuto${totalMin === 1 ? "" : "s"}`;
  const horas = Math.floor(totalMin / 60);
  const minutosRestantes = totalMin % 60;
  return `~${horas}h${minutosRestantes > 0 ? ` ${minutosRestantes}min` : ""}`;
}

// Etapas que reporta el backend mientras se genera la Ficha RUC (ver
// core_scraper/adapter.py::generar_ficha_ruc_pdf y app/jobs.py) -- el
// porcentaje es una estimacion fija por etapa (no hay forma de medir
// tiempo real dentro de una sesion de Selenium), pero le da al usuario una
// idea de cuanto falta en vez de un spinner sin contexto. null = todavia
// no llego el primer reporte del adaptador (recien encolado / arrancando
// el navegador).
const ETAPAS_FICHA_RUC = {
  null: { porcentaje: 8, etiqueta: "Iniciando..." },
  iniciando_sesion: { porcentaje: 20, etiqueta: "Abriendo SUNAT..." },
  autenticando: { porcentaje: 40, etiqueta: "Iniciando sesion..." },
  abriendo_ficha: { porcentaje: 60, etiqueta: "Abriendo la Ficha RUC..." },
  generando_pdf: { porcentaje: 85, etiqueta: "Generando el PDF..." },
  guardando: { porcentaje: 95, etiqueta: "Guardando..." },
};

function infoEtapaFichaRuc(etapa) {
  return ETAPAS_FICHA_RUC[etapa || "null"] || ETAPAS_FICHA_RUC.null;
}

// Mismo patron que ETAPAS_FICHA_RUC, para la consulta manual de una sola
// empresa (boton "Consultar" de cada tarjeta) -- ver
// core_scraper/adapter.py::consultar_buzon y app/jobs.py.
const ETAPAS_CONSULTA = {
  null: { porcentaje: 5, etiqueta: "Iniciando..." },
  iniciando_sesion: { porcentaje: 15, etiqueta: "Abriendo SUNAT..." },
  autenticando: { porcentaje: 30, etiqueta: "Iniciando sesion..." },
  leyendo_estado: { porcentaje: 50, etiqueta: "Leyendo estado del contribuyente..." },
  abriendo_buzon: { porcentaje: 65, etiqueta: "Abriendo el buzon..." },
  leyendo_mensajes: { porcentaje: 80, etiqueta: "Leyendo mensajes..." },
  descargando_documentos: { porcentaje: 92, etiqueta: "Descargando documentos nuevos..." },
};

function infoEtapaConsulta(etapa) {
  return ETAPAS_CONSULTA[etapa || "null"] || ETAPAS_CONSULTA.null;
}

// Texto relativo simple ("hace 5 min", "hace 2h", "hace 3d") -- sin
// libreria externa, solo para que el usuario vea de un vistazo si la
// Ficha RUC guardada puede estar desactualizada.
function formatoRelativo(fechaIso) {
  if (!fechaIso) return "";
  const diffMs = Date.now() - new Date(fechaIso).getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "hace un momento";
  if (diffMin < 60) return `hace ${diffMin} min`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `hace ${diffH}h`;
  const diffD = Math.floor(diffH / 24);
  return `hace ${diffD}d`;
}

// Fix Fase R4: useSearchParams() exige un limite de Suspense en el build de
// produccion (next build) -- next dev nunca lo exigia, por eso no se habia
// visto hasta ahora. EmpresasPage queda como wrapper delgado; toda la
// logica real sigue en EmpresasPageContenido, sin cambios.
export default function EmpresasPage() {
  return (
    <Suspense fallback={null}>
      <EmpresasPageContenido />
    </Suspense>
  );
}

function EmpresasPageContenido() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [empresas, setEmpresas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [consultando, setConsultando] = useState({});
  const [progresoConsulta, setProgresoConsulta] = useState({}); // { [empresaId]: {estado, etapa} }
  const [consultandoTodas, setConsultandoTodas] = useState(false);
  const [mostrarForm, setMostrarForm] = useState(false);
  const [mostrarImportar, setMostrarImportar] = useState(false);
  const [busqueda, setBusqueda] = useState("");
  // El Dashboard enlaza aca con ?hoy=1 para llegar directo con el filtro activado.
  const [soloHoy, setSoloHoy] = useState(searchParams.get("hoy") === "1");
  const [pdfRapido, setPdfRapido] = useState(null); // {empresaId, mensaje} | null
  const [estadoConsultas, setEstadoConsultas] = useState(null);
  const [generandoFicha, setGenerandoFicha] = useState({});
  const [progresoFicha, setProgresoFicha] = useState({}); // { [empresaId]: {estado, etapa} }
  const [fichaRucModal, setFichaRucModal] = useState(null); // {empresaId, razonSocial, generadaEn} | null
  const [entrandoDirecto, setEntrandoDirecto] = useState({}); // { [empresaId]: boolean }
  const [marcandoTodoLeido, setMarcandoTodoLeido] = useState(false);
  const enCursoAnteriorRef = useRef(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    cargar();
    // Pre-calienta el ingreso directo apenas se abre esta pantalla (ver
    // lib/api.js::prewarmIngresoDirecto y backend/app/ingreso_directo_cache.py)
    // -- fire-and-forget: no importa si tarda o si falla, el boton "Ir a
    // SUNAT" de cada tarjeta funciona igual sin esto, solo que mas lento.
    api.prewarmIngresoDirecto().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll del progreso de la tanda de consultas actual -- refleja tanto lo
  // que dispara este mismo boton como lo que dispare el chequeo automatico
  // (11am/7:30pm) si el usuario tiene esta pagina abierta en ese momento.
  useEffect(() => {
    if (!getToken()) return;
    let cancelado = false;
    async function poll() {
      try {
        const data = await api.estadoConsultas();
        if (!cancelado) setEstadoConsultas(data);
      } catch (err) {
        // silencioso -- un poll fallido no debe interrumpir la pagina
      }
    }
    poll();
    const intervalo = setInterval(poll, 5000);
    return () => {
      cancelado = true;
      clearInterval(intervalo);
    };
  }, []);

  // Cuando una tanda que estaba en curso termina, refresca la lista sola
  // para que los nuevos pendientes/mensajes aparezcan sin que el usuario
  // tenga que recargar la pagina a mano.
  useEffect(() => {
    if (enCursoAnteriorRef.current && estadoConsultas && !estadoConsultas.en_curso) {
      cargar();
    }
    if (estadoConsultas) enCursoAnteriorRef.current = estadoConsultas.en_curso;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [estadoConsultas]);

  async function cargar() {
    setCargando(true);
    setError("");
    try {
      const data = await api.listarEmpresas();
      setEmpresas(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setCargando(false);
    }
  }

  // Polea el job de la consulta cada 2s y va guardando la etapa reportada
  // en progresoConsulta -- mismo patron que esperarJobFichaRuc, para que
  // el boton "Consultar" de la tarjeta muestre una barra de progreso real
  // en vez de un spinner sin perspectiva de tiempo.
  async function esperarJob(empresaId, jobId) {
    for (let i = 0; i < 90; i++) {
      const job = await api.obtenerJob(jobId);
      setProgresoConsulta((prev) => ({ ...prev, [empresaId]: { estado: job.estado, etapa: job.etapa } }));
      if (job.estado === "completado" || job.estado === "error") {
        return job;
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new Error("La consulta esta tardando mas de lo esperado. Revisa el historial mas tarde.");
  }

  async function consultarAhora(empresaId) {
    setConsultando((prev) => ({ ...prev, [empresaId]: true }));
    setProgresoConsulta((prev) => ({ ...prev, [empresaId]: { estado: "pendiente", etapa: null } }));
    try {
      const job = await api.consultarEmpresa(empresaId);
      const jobFinal = await esperarJob(empresaId, job.id);
      if (jobFinal.estado === "error") {
        alert(`La consulta fallo: ${jobFinal.error || "error desconocido"}`);
      } else if (jobFinal.mensajes_nuevos > 0) {
        alert(`Listo: ${jobFinal.mensajes_nuevos} mensaje(s) nuevo(s) encontrados.`);
      } else {
        alert("Listo: no hay mensajes nuevos.");
      }
      await cargar();
    } catch (err) {
      alert(err.message);
    } finally {
      setConsultando((prev) => ({ ...prev, [empresaId]: false }));
      setProgresoConsulta((prev) => {
        const copia = { ...prev };
        delete copia[empresaId];
        return copia;
      });
    }
  }

  async function marcarTodoComoLeidoGlobal() {
    if (!confirm("Esto va a marcar como leidos TODOS los mensajes pendientes de TODAS tus empresas. Continuar?")) {
      return;
    }
    setMarcandoTodoLeido(true);
    try {
      const resultado = await api.marcarTodosLeidosGlobal();
      alert(
        resultado.actualizados === 0
          ? "No habia mensajes pendientes en ninguna empresa."
          : `Listo: ${resultado.actualizados} mensaje(s) marcado(s) como leido(s).`
      );
      await cargar();
    } catch (err) {
      alert(err.message);
    } finally {
      setMarcandoTodoLeido(false);
    }
  }

  async function consultarTodas() {
    const cantidad = empresas.filter((e) => e.activo).length;
    // Espaciadas ~45s entre si para no parecer trafico sospechoso ante
    // SUNAT (ver ESPACIADO_CONSULTAR_TODAS_SEG en el backend) -- con
    // varias decenas de empresas esto es realmente HORAS, no "unos
    // minutos" como decia antes este mensaje (eso hacia parecer que el
    // boton estaba colgado cuando en realidad estaba avanzando bien,
    // solo que muy despacio por diseño).
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

  // Polea el job de Ficha RUC cada 2s y va guardando la etapa reportada en
  // progresoFicha -- asi el boton de la tarjeta puede mostrar una barra de
  // progreso real (con etiqueta de la etapa actual) en vez de un spinner
  // opaco sin perspectiva de cuanto falta.
  async function esperarJobFichaRuc(empresaId, jobId) {
    for (let i = 0; i < 90; i++) {
      const job = await api.obtenerJobFichaRuc(empresaId, jobId);
      setProgresoFicha((prev) => ({ ...prev, [empresaId]: { estado: job.estado, etapa: job.etapa } }));
      if (job.estado === "completado" || job.estado === "error") {
        return job;
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new Error("La generacion de la Ficha RUC esta tardando mas de lo esperado. Intenta de nuevo en un momento.");
  }

  // Si ya se genero una Ficha RUC antes Y no se pide forzar, la abre
  // directo (rapido, sin volver a entrar a SUNAT). Si no existe todavia, o
  // si forzarRegenerar=true (el usuario pidio explicitamente una version
  // nueva porque la guardada puede estar desactualizada), primero la
  // genera en vivo y recien despues la abre.
  async function verFichaRuc(empresa, forzarRegenerar = false) {
    setGenerandoFicha((prev) => ({ ...prev, [empresa.id]: true }));
    setProgresoFicha((prev) => ({ ...prev, [empresa.id]: { estado: "pendiente", etapa: null } }));
    try {
      let generadaEn = empresa.ficha_ruc_generada_en;
      if (forzarRegenerar || !empresa.ficha_ruc_generada_en) {
        const job = await api.generarFichaRuc(empresa.id);
        const jobFinal = await esperarJobFichaRuc(empresa.id, job.id);
        if (jobFinal.estado === "error") {
          alert(`No se pudo generar la Ficha RUC: ${jobFinal.error || "error desconocido"}`);
          return;
        }
        generadaEn = new Date().toISOString();
        cargar(); // refresca en segundo plano para que quede marcada como ya generada
      }
      setFichaRucModal({ empresa, empresaId: empresa.id, razonSocial: empresa.razon_social, generadaEn });
    } catch (err) {
      alert(err.message);
    } finally {
      setGenerandoFicha((prev) => ({ ...prev, [empresa.id]: false }));
      setProgresoFicha((prev) => {
        const copia = { ...prev };
        delete copia[empresa.id];
        return copia;
      });
    }
  }

  async function togglePausa(empresa) {
    try {
      await api.actualizarEmpresa(empresa.id, { activo: !empresa.activo });
      cargar();
    } catch (err) {
      alert(err.message);
    }
  }

  // "Ingreso directo": abre una pestana nueva ya logueada en Operaciones en
  // Linea de SUNAT, sin escribir nada. Vive ACA (en la tarjeta, no en el
  // detalle del buzon) porque este es el mismo lugar donde ya estaba el
  // enlace manual a Operaciones en Linea -- tiene mas sentido reemplazar
  // ese boton que agregar uno nuevo en otra pantalla. Se abre la pestana
  // VACIA primero (en el mismo tick del clic, antes de cualquier await)
  // porque los navegadores bloquean como popup una pestana que se abre
  // despues de una espera asincrona -- despues se le cambia la ubicacion
  // cuando llega el token. Tarda 15-30 segundos en cargar (el backend hace
  // un login de prueba con Selenium solo para conseguir los datos frescos
  // que pide SUNAT en ese momento) -- la pestana muestra una pagina de
  // "Entrando a SUNAT..." mientras tanto.
  async function entrarDirectoASunat(empresaId) {
    const pestana = window.open("", "_blank");
    setEntrandoDirecto((prev) => ({ ...prev, [empresaId]: true }));
    try {
      const { token } = await api.obtenerTokenIngresoDirecto(empresaId);
      if (pestana) {
        pestana.location.href = `${API_URL}/empresas/${empresaId}/ingreso-directo?token=${encodeURIComponent(token)}`;
      }
    } catch (err) {
      if (pestana) pestana.close();
      alert(err.message);
    } finally {
      setEntrandoDirecto((prev) => ({ ...prev, [empresaId]: false }));
    }
  }

  const textoBusqueda = busqueda.trim().toLowerCase();
  const empresasFiltradas = empresas.filter((e) => {
    const coincideBusqueda =
      textoBusqueda === "" ||
      e.razon_social.toLowerCase().includes(textoBusqueda) ||
      e.ruc.includes(textoBusqueda);
    const coincideHoy = !soloHoy || e.mensajes_hoy > 0;
    return coincideBusqueda && coincideHoy;
  });
  const empresasConNovedadesHoy = empresas.filter((e) => e.mensajes_hoy > 0).length;

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 py-8 xl:px-12">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-ink">Empresas</h1>
            <p className="mt-1 text-sm text-slate-600">Empresas que estas monitoreando</p>
          </div>

          <div className="flex flex-wrap gap-2">
            <BotonConsultarTodas
              onClick={consultarTodas}
              consultando={consultandoTodas}
              estado={estadoConsultas}
              disabled={empresas.length === 0}
            />
            <button
              onClick={marcarTodoComoLeidoGlobal}
              disabled={marcandoTodoLeido || empresas.length === 0}
              title="Marca como leidos todos los mensajes pendientes, de todas las empresas"
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition-all duration-300 ease-out hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {marcandoTodoLeido ? (
                <Loader2 size={15} strokeWidth={1.5} className="animate-spin" />
              ) : (
                <CheckCheck size={15} strokeWidth={1.5} />
              )}
              Marcar todo como leido
            </button>
            <button
              onClick={() => {
                setMostrarForm((v) => !v);
                setMostrarImportar(false);
              }}
              className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark"
            >
              {mostrarForm ? <X size={15} strokeWidth={1.5} /> : <Plus size={15} strokeWidth={1.5} />}
              {mostrarForm ? "Cancelar" : "Agregar empresa"}
            </button>
            <button
              onClick={() => {
                setMostrarImportar((v) => !v);
                setMostrarForm(false);
              }}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition-all duration-300 ease-out hover:border-slate-300 hover:bg-slate-50"
            >
              {mostrarImportar ? <X size={15} strokeWidth={1.5} /> : <Upload size={15} strokeWidth={1.5} />}
              {mostrarImportar ? "Cancelar" : "Importar desde Excel"}
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-6 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
        )}

        {mostrarForm && (
          <FormularioEmpresa
            onCreada={() => {
              setMostrarForm(false);
              cargar();
            }}
          />
        )}

        {mostrarImportar && <FormularioImportar onImportado={() => cargar()} />}

        {cargando ? (
          <p className="mt-8 text-sm text-slate-500">Cargando...</p>
        ) : empresas.length === 0 ? (
          <p className="mt-8 text-sm text-slate-500">Todavia no agregaste ninguna empresa.</p>
        ) : (
          <>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <div className="relative max-w-md flex-1 min-w-[220px]">
                <Search size={16} strokeWidth={1.5} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  value={busqueda}
                  onChange={(e) => setBusqueda(e.target.value)}
                  placeholder="Buscar por razon social o RUC..."
                  className="campo-input pl-9"
                />
              </div>
              <button
                onClick={() => setSoloHoy((v) => !v)}
                className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-3.5 py-2.5 text-sm font-medium transition-all duration-300 ease-out ${
                  soloHoy
                    ? "border-accent bg-accent text-white"
                    : "border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50"
                }`}
              >
                <Sparkles size={15} strokeWidth={1.5} />
                Con novedades hoy
                {empresasConNovedadesHoy > 0 && (
                  <span
                    className={`rounded-full px-1.5 text-xs ${
                      soloHoy ? "bg-white/20" : "bg-accent-light text-accent"
                    }`}
                  >
                    {empresasConNovedadesHoy}
                  </span>
                )}
              </button>
            </div>

            <p className="mt-4 text-xs font-medium uppercase tracking-wide text-slate-400">
              {empresasFiltradas.length} de {empresas.length} empresa{empresas.length === 1 ? "" : "s"}
            </p>

            {empresasFiltradas.length === 0 ? (
              <p className="mt-8 text-sm text-slate-500">Ninguna empresa calza con la busqueda/filtro actual.</p>
            ) : (
              <div className="mt-3 grid grid-cols-1 gap-5 md:grid-cols-2">
                {empresasFiltradas.map((e) => (
                  <TarjetaEmpresa
                    key={e.id}
                    empresa={e}
                    consultando={!!consultando[e.id]}
                    progresoConsulta={progresoConsulta[e.id]}
                    onConsultar={() => consultarAhora(e.id)}
                    onTogglePausa={() => togglePausa(e)}
                    onVerPdfRapido={() => setPdfRapido({ empresaId: e.id, mensaje: e.ultimo_mensaje })}
                    generandoFicha={!!generandoFicha[e.id]}
                    progresoFicha={progresoFicha[e.id]}
                    onVerFichaRuc={() => verFichaRuc(e, false)}
                    onRegenerarFichaRuc={() => verFichaRuc(e, true)}
                    entrandoDirecto={!!entrandoDirecto[e.id]}
                    onEntrarDirecto={() => entrarDirectoASunat(e.id)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </main>

      {pdfRapido && <ModalPdfRapido info={pdfRapido} onClose={() => setPdfRapido(null)} />}
      {fichaRucModal && (
        <ModalFichaRuc
          info={fichaRucModal}
          onClose={() => setFichaRucModal(null)}
          onRegenerar={() => {
            const empresa = fichaRucModal.empresa;
            setFichaRucModal(null);
            verFichaRuc(empresa, true);
          }}
        />
      )}
    </div>
  );
}

function BotonConsultarTodas({ onClick, consultando, estado, disabled }) {
  const enCurso = !!estado?.en_curso;
  const ocupado = consultando || enCurso;
  const porcentaje = enCurso && estado.total > 0 ? Math.round((estado.completados / estado.total) * 100) : 0;

  return (
    <div className="group relative">
      <button
        onClick={onClick}
        disabled={ocupado || disabled}
        className="flex items-center gap-1.5 rounded-lg border border-accent/30 bg-accent-light px-4 py-2 text-sm font-semibold text-accent transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
      >
        {ocupado ? (
          <Loader2 size={15} strokeWidth={1.5} className="animate-spin" />
        ) : (
          <Zap size={15} strokeWidth={1.5} />
        )}
        {enCurso
          ? `Consultando ${estado.completados}/${estado.total}`
          : consultando
          ? "Encolando..."
          : "Consultar todas"}
      </button>

      {/* "Nube" con el avance -- aparece al pasar el mouse mientras hay una
          tanda en curso, sea porque el usuario la disparo desde aca o
          porque la disparo el chequeo automatico (11am/7:30pm). */}
      {enCurso && (
        <div className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 w-60 -translate-x-1/2 opacity-0 transition-opacity duration-200 ease-out group-hover:opacity-100">
          <div className="absolute -top-1.5 left-1/2 h-3 w-3 -translate-x-1/2 rotate-45 rounded-sm bg-ink" />
          <div className="rounded-xl bg-ink px-3.5 py-3 text-white shadow-soft-lg">
            <div className="flex items-center justify-between text-xs font-semibold">
              <span>Consulta masiva en curso</span>
              <span>{porcentaje}%</span>
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/20">
              <div
                className="h-full rounded-full bg-accent transition-all duration-500"
                style={{ width: `${porcentaje}%` }}
              />
            </div>
            <p className="mt-2 text-[11px] text-slate-300">
              {estado.completados} completada{estado.completados === 1 ? "" : "s"}, {estado.pendientes + estado.en_progreso} en cola
              {estado.con_error > 0 ? `, ${estado.con_error} con error` : ""}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function TarjetaEmpresa({
  empresa: e,
  consultando,
  progresoConsulta,
  onConsultar,
  onTogglePausa,
  onVerPdfRapido,
  generandoFicha,
  progresoFicha,
  onVerFichaRuc,
  onRegenerarFichaRuc,
  entrandoDirecto,
  onEntrarDirecto,
}) {
  return (
    <div className="surface-card animate-fade-in-up p-6 transition-all duration-300 ease-out hover:-translate-y-0.5 hover:shadow-soft-lg">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/empresas/${e.id}`}
            className="block line-clamp-2 text-lg font-bold leading-snug tracking-tight text-ink hover:text-accent"
            title={e.razon_social}
          >
            {e.razon_social}
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <p className="text-sm text-slate-500">{e.ruc}</p>
            {e.mensajes_hoy > 0 && (
              <Link
                href={`/empresas/${e.id}?filtro=hoy`}
                className="flex items-center gap-1 rounded-full bg-accent-light px-2 py-0.5 text-[11px] font-semibold text-accent transition-colors duration-300 ease-out hover:bg-blue-100"
              >
                <Sparkles size={10} strokeWidth={1.5} />
                {e.mensajes_hoy} hoy
              </Link>
            )}
          </div>
        </div>
        <button
          onClick={onTogglePausa}
          className={`flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide transition-colors duration-300 ease-out ${
            e.activo
              ? "bg-accent-light text-accent hover:bg-blue-100"
              : "bg-slate-100 text-slate-500 hover:bg-slate-200"
          }`}
        >
          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${e.activo ? "bg-accent" : "bg-slate-400"}`} />
          {e.activo ? "Activa" : "Pausada"}
        </button>
      </div>

      {e.estado_contribuyente ? (
        e.estado_contribuyente.toUpperCase() !== "ACTIVO" ? (
          <div className="mt-3 flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-700">
            <AlertTriangle size={14} strokeWidth={1.5} className="shrink-0" />
            Estado del contribuyente: {e.estado_contribuyente} -- puede afectar la declaracion de impuestos
          </div>
        ) : (
          <div className="mt-3 flex items-center gap-1.5 text-xs text-slate-400">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
            Estado del contribuyente: Activo
          </div>
        )
      ) : null}

      {e.condicion_domicilio ? (
        e.condicion_domicilio !== "Habido" ? (
          <div className="mt-1.5 flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-700">
            <AlertTriangle size={14} strokeWidth={1.5} className="shrink-0" />
            Domicilio fiscal: {e.condicion_domicilio} -- puede afectar la declaracion de impuestos
          </div>
        ) : (
          <div className="mt-1.5 flex items-center gap-1.5 text-xs text-slate-400">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
            Domicilio fiscal: Habido
          </div>
        )
      ) : null}

      {/* Fila compacta de accesos rapidos -- antes eran 4 bloques grandes en
          grilla 2x2; ahora son pills chicas en una sola fila (se envuelve
          si hace falta) para que no dominen la tarjeta. Pendientes y
          Mensajes abren el detalle de la empresa, "Ir a SUNAT" abre
          Operaciones en Linea ya logueado, y Ficha RUC genera/abre el PDF. */}
      <div className="mt-4 flex flex-wrap items-center gap-1.5">
        <Link
          href={`/empresas/${e.id}?filtro=pendientes`}
          title="Pendientes"
          className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-bold transition-all duration-300 ease-out hover:-translate-y-0.5 ${
            e.pendientes > 0 ? "bg-accent-light text-accent" : "bg-slate-50 text-slate-500"
          }`}
        >
          <Inbox size={13} strokeWidth={2} />
          {e.pendientes}
        </Link>

        <Link
          href={`/empresas/${e.id}`}
          title="Mensajes"
          className="inline-flex items-center gap-1.5 rounded-lg bg-slate-50 px-2.5 py-1.5 text-xs font-bold text-ink transition-all duration-300 ease-out hover:-translate-y-0.5"
        >
          <Mail size={13} strokeWidth={2} />
          {e.total_mensajes}
        </Link>

        <button
          onClick={onEntrarDirecto}
          disabled={entrandoDirecto}
          title="Entra directo a Operaciones en Linea de SUNAT, ya logueado, sin escribir nada."
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-50 px-2.5 py-1.5 text-xs font-bold text-emerald-700 transition-all duration-300 ease-out hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
        >
          {entrandoDirecto ? (
            <Loader2 size={13} strokeWidth={2} className="animate-spin" />
          ) : (
            <LogIn size={13} strokeWidth={2} />
          )}
          {entrandoDirecto ? "Entrando..." : "Ir a SUNAT"}
        </button>
        <a
          href={URL_SUNAT_MENU}
          target="_blank"
          rel="noopener noreferrer"
          title="Abrir manualmente el Menu SOL de SUNAT (plan B si el ingreso automatico falla)"
          className="inline-flex items-center justify-center rounded-lg p-1.5 text-slate-400 transition-colors duration-300 ease-out hover:bg-slate-100 hover:text-emerald-600"
        >
          <ExternalLink size={12} strokeWidth={2} />
        </a>

        <button
          onClick={onVerFichaRuc}
          disabled={generandoFicha}
          title={
            e.ficha_ruc_generada_en
              ? "Ver el PDF de la Ficha RUC ya generado"
              : "Genera el PDF de la Ficha RUC entrando en vivo a SUNAT"
          }
          className="inline-flex items-center gap-1.5 rounded-lg bg-violet-50 px-2.5 py-1.5 text-xs font-bold text-violet-700 transition-all duration-300 ease-out hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:hover:translate-y-0"
        >
          {generandoFicha ? (
            <Loader2 size={13} strokeWidth={2} className="animate-spin" />
          ) : (
            <IdCard size={13} strokeWidth={2} />
          )}
          {generandoFicha
            ? `${infoEtapaFichaRuc(progresoFicha?.etapa).porcentaje}%`
            : e.ficha_ruc_generada_en
            ? "Ver Ficha"
            : "Ficha RUC"}
        </button>
        {e.ficha_ruc_generada_en && !generandoFicha && (
          <button
            onClick={onRegenerarFichaRuc}
            title="Generar una version nueva de la Ficha RUC (por si la guardada quedo desactualizada)"
            className="inline-flex items-center justify-center rounded-lg p-1.5 text-slate-400 transition-colors duration-300 ease-out hover:bg-slate-100 hover:text-violet-600"
          >
            <RefreshCw size={12} strokeWidth={2} />
          </button>
        )}
      </div>

      {e.ultimo_mensaje && (
        <div className="mt-4 rounded-xl border border-slate-100 bg-slate-50/60 p-3.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">Ultimo mensaje</span>
            {e.ultimo_mensaje.tipo && (
              <span
                title={e.ultimo_mensaje.tipo}
                className={`max-w-[60%] shrink-0 truncate rounded px-1.5 py-0.5 text-[10px] font-semibold leading-4 ${colorBadgeTipo(e.ultimo_mensaje.tipo)}`}
              >
                {e.ultimo_mensaje.tipo}
              </span>
            )}
          </div>
          <div className="mt-1.5 flex items-center justify-between gap-2">
            <p className="min-w-0 flex-1 truncate text-sm text-ink" title={e.ultimo_mensaje.asunto}>
              {e.ultimo_mensaje.asunto}
            </p>
            {e.ultimo_mensaje.tiene_documento ? (
              <button
                onClick={onVerPdfRapido}
                className="flex shrink-0 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 transition-all duration-300 ease-out hover:border-accent hover:text-accent"
              >
                <FileText size={12} strokeWidth={1.5} />
                Ver PDF
              </button>
            ) : (
              <Link
                href={`/empresas/${e.id}`}
                className="flex shrink-0 items-center gap-1 text-xs font-medium text-slate-400 hover:text-accent"
              >
                Ver <ArrowRight size={12} strokeWidth={1.5} />
              </Link>
            )}
          </div>
        </div>
      )}

      <div className="mt-4 border-t border-slate-100 pt-4">
        <span className="block truncate text-xs text-slate-400">
          {e.ultima_consulta_en ? `Ultima vez: ${new Date(e.ultima_consulta_en).toLocaleDateString()}` : "Sin consultar"}
          <span className="text-slate-300"> &middot; </span>
          {e.total_consultas} consulta{e.total_consultas === 1 ? "" : "s"}
        </span>
        <div className="mt-3">
          <button
            disabled={consultando}
            onClick={onConsultar}
            className="flex w-full flex-col items-center justify-center gap-1.5 rounded-lg border border-slate-200 px-3.5 py-2 text-xs font-semibold text-slate-700 transition-all duration-300 ease-out hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-60"
          >
            {consultando ? (
              <>
                {/* Barra de progreso con etapa -- misma idea que el boton de
                    Ficha RUC: perspectiva real de cuanto falta en vez de un
                    spinner sin contexto. */}
                <div className="flex items-center gap-1.5">
                  <Loader2 size={14} strokeWidth={1.5} className="animate-spin" />
                  <span>
                    {infoEtapaConsulta(progresoConsulta?.etapa).etiqueta} ({infoEtapaConsulta(progresoConsulta?.etapa).porcentaje}%)
                  </span>
                </div>
                <div className="h-1 w-full max-w-[220px] overflow-hidden rounded-full bg-slate-200">
                  <div
                    className="h-full rounded-full bg-accent transition-all duration-500"
                    style={{ width: `${infoEtapaConsulta(progresoConsulta?.etapa).porcentaje}%` }}
                  />
                </div>
              </>
            ) : (
              <div className="flex items-center gap-1.5">
                <RefreshCw size={14} strokeWidth={1.5} />
                Consultar
              </div>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

function ModalPdfRapido({ info, onClose }) {
  const [url, setUrl] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelado = false;
    setCargando(true);
    setError("");
    api
      .obtenerDocumentoUrl(info.empresaId, info.mensaje.id)
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
  }, [info.mensaje.id]);

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
          <span className="truncate text-sm font-semibold text-ink">{info.mensaje.asunto}</span>
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
          <iframe src={url} title={info.mensaje.asunto} className="flex-1 border-0" />
        )}
      </div>
    </div>
  );
}

function ModalFichaRuc({ info, onClose, onRegenerar }) {
  const [url, setUrl] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelado = false;
    setCargando(true);
    setError("");
    api
      .obtenerFichaRucPdfUrl(info.empresaId)
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
  }, [info.empresaId]);

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
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
          <div className="min-w-0">
            <span className="block truncate text-sm font-semibold text-ink">Ficha RUC -- {info.razonSocial}</span>
            {info.generadaEn && (
              <span className="text-xs text-slate-400">
                Generada {formatoRelativo(info.generadaEn)} -- puede estar desactualizada si algo cambio despues
              </span>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              onClick={onRegenerar}
              title="Vuelve a entrar a SUNAT y genera una version nueva (tarda cerca de un minuto)"
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 transition-all duration-300 ease-out hover:border-violet-300 hover:text-violet-700"
            >
              <RefreshCw size={13} strokeWidth={1.5} />
              Generar de nuevo
            </button>
            <button
              onClick={cerrar}
              className="flex items-center justify-center rounded-lg p-1.5 text-slate-500 transition-colors duration-300 ease-out hover:bg-slate-100 hover:text-ink"
              aria-label="Cerrar"
            >
              <X size={18} strokeWidth={1.5} />
            </button>
          </div>
        </div>
        {cargando ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-slate-400">
            <Loader2 size={24} strokeWidth={1.5} className="animate-spin" />
            <p className="text-sm">Cargando Ficha RUC...</p>
          </div>
        ) : error ? (
          <div className="flex h-full items-center justify-center p-8 text-center text-sm text-red-600">{error}</div>
        ) : (
          <iframe src={url} title={`Ficha RUC -- ${info.razonSocial}`} className="flex-1 border-0" />
        )}
      </div>
    </div>
  );
}

function FormularioEmpresa({ onCreada }) {
  const [ruc, setRuc] = useState("");
  const [razonSocial, setRazonSocial] = useState("");
  const [usuarioSol, setUsuarioSol] = useState("");
  const [claveSol, setClaveSol] = useState("");
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setGuardando(true);
    try {
      await api.crearEmpresa({
        ruc,
        razon_social: razonSocial,
        usuario_sol: usuarioSol,
        clave_sol: claveSol,
      });
      onCreada();
    } catch (err) {
      setError(err.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="surface-card mt-6 animate-fade-in-up p-6">
      {error && (
        <div className="mb-4 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
      )}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Campo id="ruc" label="RUC (11 digitos)">
          <input
            id="ruc"
            value={ruc}
            onChange={(e) => setRuc(e.target.value)}
            maxLength={11}
            pattern="\d{11}"
            required
            className="campo-input"
          />
        </Campo>
        <Campo id="razonSocial" label="Razon social">
          <input
            id="razonSocial"
            value={razonSocial}
            onChange={(e) => setRazonSocial(e.target.value)}
            required
            className="campo-input"
          />
        </Campo>
        <Campo id="usuarioSol" label="Usuario SOL">
          <input
            id="usuarioSol"
            value={usuarioSol}
            onChange={(e) => setUsuarioSol(e.target.value)}
            required
            className="campo-input"
          />
        </Campo>
        <Campo id="claveSol" label="Clave SOL">
          <input
            id="claveSol"
            type="password"
            value={claveSol}
            onChange={(e) => setClaveSol(e.target.value)}
            required
            className="campo-input"
          />
        </Campo>
      </div>
      <button
        type="submit"
        disabled={guardando}
        className="mt-5 flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
      >
        {guardando && <Loader2 size={14} strokeWidth={1.5} className="animate-spin" />}
        {guardando ? "Guardando..." : "Guardar empresa"}
      </button>
    </form>
  );
}

function FormularioImportar({ onImportado }) {
  const [archivo, setArchivo] = useState(null);
  const [error, setError] = useState("");
  const [importando, setImportando] = useState(false);
  const [resultado, setResultado] = useState(null);

  async function onSubmit(e) {
    e.preventDefault();
    if (!archivo) {
      setError("Selecciona un archivo .xls o .xlsx primero.");
      return;
    }
    setError("");
    setResultado(null);
    setImportando(true);
    try {
      const data = await api.importarEmpresas(archivo);
      setResultado(data);
      onImportado();
    } catch (err) {
      setError(err.message);
    } finally {
      setImportando(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="surface-card mt-6 animate-fade-in-up p-6">
      <p className="text-sm text-slate-600">
        Sube el Excel con las columnas de RUC, usuario SOL, clave SOL y razon social (el mismo formato que ya usas
        para la automatizacion). Las empresas que ya existan se saltan, asi que puedes volver a subir el mismo
        archivo sin duplicar nada.
      </p>

      {error && (
        <div className="mt-4 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
      )}

      <label className="mt-4 flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-slate-300 px-4 py-3 text-sm text-slate-600 transition-colors duration-300 ease-out hover:border-accent hover:text-accent">
        <FileSpreadsheet size={16} strokeWidth={1.5} />
        {archivo ? archivo.name : "Seleccionar archivo .xls o .xlsx"}
        <input
          type="file"
          accept=".xls,.xlsx"
          onChange={(e) => setArchivo(e.target.files?.[0] || null)}
          className="hidden"
        />
      </label>

      <button
        type="submit"
        disabled={importando}
        className="mt-4 flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
      >
        {importando && <Loader2 size={14} strokeWidth={1.5} className="animate-spin" />}
        {importando ? "Importando..." : "Importar"}
      </button>

      {resultado && (
        <div className="mt-5">
          <p className="text-sm text-slate-700">
            <strong className="text-ink">{resultado.creadas}</strong> empresa(s) creada(s),{" "}
            <strong className="text-ink">{resultado.ya_existian}</strong> ya existian,{" "}
            <strong className="text-ink">{resultado.con_error}</strong> con error.
          </p>
          {resultado.con_error > 0 && (
            <div className="mt-3 overflow-hidden rounded-lg border border-slate-100">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                    <th className="px-4 py-2">RUC</th>
                    <th className="px-4 py-2">Detalle</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {resultado.detalle
                    .filter((item) => item.resultado === "error")
                    .map((item, i) => (
                      <tr key={i}>
                        <td className="px-4 py-2 text-slate-600">{item.ruc}</td>
                        <td className="px-4 py-2 text-red-600">{item.detalle}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </form>
  );
}

function Campo({ id, label, children }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </label>
      {children}
    </div>
  );
}
