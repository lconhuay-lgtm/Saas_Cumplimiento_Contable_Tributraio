"use client";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
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

// "Pendientes" y "X hoy" antes siempre se veian igual sin importar que
// clase de mensaje era -- una Orden de Pago sin leer se confundia con un
// mensaje informativo sin leer. Se colorean con la MISMA paleta de
// severidad que ya existe para el tipo de mensaje (colorBadgeTipo), segun
// el tipo mas severo entre lo pendiente/lo de hoy (tipo_pendiente_mas_severo/
// tipo_hoy_mas_severo, calculados en el backend -- ver
// clasificacion.tipo_mas_severo). "Otros" (o sin tipo) se trata como caso
// neutro -- nada que destacar especialmente.
function esTipoSevero(tipo) {
  return !!tipo && tipo !== "Otros";
}
import BotonConsultarTodas, { formatoDuracionEstimada } from "../../components/BotonConsultarTodas";
import ConfirmDialog from "../../components/ConfirmDialog";
import InfoDialog from "../../components/InfoDialog";
import { infoEtapaConsulta, infoEtapaFichaRuc, infoEtapaReporteTributario } from "../../lib/etapasTrabajos";
import { useTrabajos, progresoPorTipo } from "../../contexts/TrabajosContext";

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
  // Trabajos en curso (consulta, ficha RUC, reporte tributario) viven en
  // TrabajosContext -- no en estado local -- para que el progreso sobreviva
  // la navegacion a otra pantalla (ver contexts/TrabajosContext.js).
  const { trabajos, iniciarTrabajo, quitar, estadoMasiva } = useTrabajos();
  const consultando = useMemo(() => progresoPorTipo(trabajos, "consulta"), [trabajos]);
  const progresoConsulta = consultando;
  const [consultandoTodas, setConsultandoTodas] = useState(false);
  const [mostrarForm, setMostrarForm] = useState(false);
  const [mostrarImportar, setMostrarImportar] = useState(false);
  const [busqueda, setBusqueda] = useState("");
  // El Dashboard enlaza aca con ?hoy=1 para llegar directo con el filtro activado.
  const [soloHoy, setSoloHoy] = useState(searchParams.get("hoy") === "1");
  // Mismo patron que soloHoy, pero para mensajes no leidos sin importar
  // cuando llegaron (a diferencia de "hoy", que es solo lo del dia).
  const [soloPendientes, setSoloPendientes] = useState(searchParams.get("pendientes") === "1");
  const [filtroEstadoContribuyente, setFiltroEstadoContribuyente] = useState("");
  const [filtroCondicionDomicilio, setFiltroCondicionDomicilio] = useState("");
  const [filtroUltimoDigito, setFiltroUltimoDigito] = useState("");
  const [pdfRapido, setPdfRapido] = useState(null); // {empresaId, mensaje} | null
  const generandoFicha = useMemo(() => progresoPorTipo(trabajos, "ficha"), [trabajos]);
  const progresoFicha = generandoFicha;
  const [eligiendoTipoFicha, setEligiendoTipoFicha] = useState(null); // {empresa, forzarRegenerar} | null
  const [pidiendoReporteTributario, setPidiendoReporteTributario] = useState(null); // {empresa} | null
  const solicitandoReporte = useMemo(() => progresoPorTipo(trabajos, "reporte"), [trabajos]);
  const progresoReporte = solicitandoReporte;
  const [entrandoDirecto, setEntrandoDirecto] = useState({}); // { [empresaId]: boolean }
  const [entrandoDeclaraciones, setEntrandoDeclaraciones] = useState({}); // { [empresaId]: boolean }
  const [entrandoRentaAnual, setEntrandoRentaAnual] = useState({}); // { [empresaId]: boolean }
  const [marcandoTodoLeido, setMarcandoTodoLeido] = useState(false);
  const masivaEnCursoAnteriorRef = useRef(false);
  // Reemplazan los alert() nativos que solo avisaban un resultado (no
  // pedian confirmacion) -- ver InfoDialog. {titulo, mensaje, variante} | null
  const [resultadoConsulta, setResultadoConsulta] = useState(null);

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

  // El poll de GET /consultas/estado y el dialogo de resumen final ahora
  // viven en TrabajosContext (persisten aunque el usuario navegue a otra
  // pantalla o cierre esta pestana -- ver ese archivo). Aca solo queda
  // refrescar la lista propia de esta pantalla cuando una tanda que estaba
  // en curso termina, para que los nuevos pendientes/mensajes aparezcan
  // sin que el usuario tenga que recargar a mano.
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
      const data = await api.listarEmpresas();
      setEmpresas(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setCargando(false);
    }
  }

  async function consultarAhora(empresaId) {
    const empresaNombre = empresas.find((x) => x.id === empresaId)?.razon_social;
    try {
      const job = await api.consultarEmpresa(empresaId);
      // El polling real vive en TrabajosContext (sobrevive si el usuario
      // navega a otra pantalla mientras espera) -- ver esa funcion para el
      // detalle de reintentos (200 x 3s = 10 min, igual al job_timeout del
      // servidor).
      const jobFinal = await iniciarTrabajo("consulta", empresaId, empresaNombre, job.id);
      if (jobFinal.estado === "error") {
        // A pedido: no se muestra el detalle tecnico crudo (jobFinal.error
        // puede traer un stacktrace de Selenium) -- el usuario no puede
        // hacer nada con eso, y la consulta ya se reintento sola una vez
        // (ver MAX_INTENTOS en jobs.py) antes de llegar a este punto.
        setResultadoConsulta({
          titulo: "La consulta no se pudo completar",
          mensaje: "Intenta de nuevo en unos minutos.",
          variante: "error",
        });
      } else if (jobFinal.mensajes_nuevos > 0) {
        setResultadoConsulta({
          titulo: "Consulta completada",
          mensaje: `${jobFinal.mensajes_nuevos} mensaje(s) nuevo(s) encontrados.`,
          variante: "ok",
        });
      } else {
        setResultadoConsulta({
          titulo: "Consulta completada",
          mensaje: "No hay mensajes nuevos.",
          variante: "info",
        });
      }
      await cargar();
    } catch (err) {
      setResultadoConsulta({ titulo: "La consulta fallo", mensaje: err.message, variante: "error" });
    } finally {
      quitar("consulta", empresaId);
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

  // Muestra primero la eleccion Con QR / Sin QR (a pedido: el "Reporte de
  // Ficha RUC" con QR es un documento distinto al de siempre, y SUNAT lo
  // limita a 3 generaciones por dia por empresa) -- recien con la
  // respuesta se llama a verFichaRuc con el tipo elegido.
  function pedirTipoFichaRuc(empresa, forzarRegenerar = false) {
    setEligiendoTipoFicha({ empresa, forzarRegenerar });
  }

  // Si ya se genero una Ficha RUC de este tipo antes Y no se pide forzar,
  // la descarga directo (rapido, sin volver a entrar a SUNAT). Si no
  // existe todavia, o si forzarRegenerar=true (el usuario pidio
  // explicitamente una version nueva porque la guardada puede estar
  // desactualizada), primero la genera en vivo y recien despues la
  // descarga. A pedido: descarga directa al disco del usuario en vez de
  // mostrarla dentro de la app (mas simple, y el archivo queda listo para
  // archivar/reenviar, que es el uso real que le da un estudio contable).
  async function verFichaRuc(empresa, forzarRegenerar = false, conQr = false) {
    try {
      const yaGeneradaEn = conQr ? empresa.ficha_ruc_qr_generada_en : empresa.ficha_ruc_generada_en;
      if (forzarRegenerar || !yaGeneradaEn) {
        const job = await api.generarFichaRuc(empresa.id, conQr);
        // El polling real vive en TrabajosContext -- sobrevive si el
        // usuario navega a otra pantalla mientras la Ficha RUC se genera.
        const jobFinal = await iniciarTrabajo("ficha", empresa.id, empresa.razon_social, job.id);
        if (jobFinal.estado === "error") {
          alert(`No se pudo generar la Ficha RUC: ${jobFinal.error || "error desconocido"}`);
          return;
        }
        cargar(); // refresca en segundo plano para que quede marcada como ya generada
      }
      const url = await api.obtenerFichaRucPdfUrl(empresa.id, conQr);
      const nombreArchivo = `${conQr ? "reporte-ficha-ruc-qr" : "ficha-ruc"}-${empresa.ruc}.pdf`;
      const enlace = document.createElement("a");
      enlace.href = url;
      enlace.download = nombreArchivo;
      document.body.appendChild(enlace);
      enlace.click();
      document.body.removeChild(enlace);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      alert(err.message);
    } finally {
      quitar("ficha", empresa.id);
    }
  }

  function pedirReporteTributario(empresa) {
    setPidiendoReporteTributario({ empresa });
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
  // Devuelve la pestana abierta (o null si fallo) -- el Reporte Tributario la
  // usa para seguir el ingreso y llevarla despues al formulario.
  async function entrarDirectoASunat(empresaId, nombreVentana = "_blank") {
    const pestana = window.open("", nombreVentana);
    setEntrandoDirecto((prev) => ({ ...prev, [empresaId]: true }));
    try {
      const { token } = await api.obtenerTokenIngresoDirecto(empresaId);
      if (pestana) {
        pestana.location.href = `${API_URL}/empresas/${empresaId}/ingreso-directo?token=${encodeURIComponent(token)}`;
      }
      return pestana;
    } catch (err) {
      if (pestana) pestana.close();
      alert(err.message);
      return null;
    } finally {
      setEntrandoDirecto((prev) => ({ ...prev, [empresaId]: false }));
    }
  }

  // Misma estructura y mismo mecanismo que entrarDirectoASunat -- unico
  // cambio: el destino post-login es "Mis Declaraciones y Pagos" en vez
  // del Menu SOL clasico (ver GET /ingreso-directo-declaraciones y
  // core_scraper/adapter.py::preparar_ingreso_directo_declaraciones).
  async function entrarDirectoADeclaraciones(empresaId) {
    const pestana = window.open("", "_blank");
    setEntrandoDeclaraciones((prev) => ({ ...prev, [empresaId]: true }));
    try {
      const { token } = await api.obtenerTokenIngresoDirectoDeclaraciones(empresaId);
      if (pestana) {
        pestana.location.href = `${API_URL}/empresas/${empresaId}/ingreso-directo-declaraciones?token=${encodeURIComponent(token)}`;
      }
    } catch (err) {
      if (pestana) pestana.close();
      alert(err.message);
    } finally {
      setEntrandoDeclaraciones((prev) => ({ ...prev, [empresaId]: false }));
    }
  }

  // Misma estructura y mismo mecanismo que entrarDirectoASunat -- unico
  // cambio: el destino post-login es "DJ Anual" (Declaracion Jurada Anual
  // de Renta, e-renta.sunat.gob.pe) en vez del Menu SOL clasico (ver GET
  // /ingreso-directo-renta-anual y
  // core_scraper/adapter.py::preparar_ingreso_directo_renta_anual).
  async function entrarDirectoARentaAnual(empresaId) {
    const pestana = window.open("", "_blank");
    setEntrandoRentaAnual((prev) => ({ ...prev, [empresaId]: true }));
    try {
      const { token } = await api.obtenerTokenIngresoDirectoRentaAnual(empresaId);
      if (pestana) {
        pestana.location.href = `${API_URL}/empresas/${empresaId}/ingreso-directo-renta-anual?token=${encodeURIComponent(token)}`;
      }
    } catch (err) {
      if (pestana) pestana.close();
      alert(err.message);
    } finally {
      setEntrandoRentaAnual((prev) => ({ ...prev, [empresaId]: false }));
    }
  }

  // Opciones armadas de los valores que de verdad trae SUNAT hoy (no una
  // lista fija de catalogo) -- ver comentario junto a los <select> de abajo.
  const opcionesEstadoContribuyente = useMemo(
    () => Array.from(new Set(empresas.map((e) => e.estado_contribuyente).filter(Boolean))).sort(),
    [empresas]
  );
  const opcionesCondicionDomicilio = useMemo(
    () => Array.from(new Set(empresas.map((e) => e.condicion_domicilio).filter(Boolean))).sort(),
    [empresas]
  );
  // Igual que los dos filtros de arriba: solo se listan los digitos que de
  // verdad tiene alguna empresa registrada, para no mostrar "Termina en 5"
  // si ninguna termina en 5.
  const opcionesUltimoDigito = useMemo(
    () => Array.from(new Set(empresas.map((e) => e.ruc.slice(-1)))).sort(),
    [empresas]
  );

  const textoBusqueda = busqueda.trim().toLowerCase();
  const empresasFiltradas = empresas.filter((e) => {
    const coincideBusqueda =
      textoBusqueda === "" ||
      e.razon_social.toLowerCase().includes(textoBusqueda) ||
      e.ruc.includes(textoBusqueda);
    const coincideHoy = !soloHoy || e.mensajes_hoy > 0;
    const coincidePendientes = !soloPendientes || e.pendientes > 0;
    const coincideEstado = !filtroEstadoContribuyente || e.estado_contribuyente === filtroEstadoContribuyente;
    const coincideDomicilio = !filtroCondicionDomicilio || e.condicion_domicilio === filtroCondicionDomicilio;
    const coincideDigito = !filtroUltimoDigito || e.ruc.slice(-1) === filtroUltimoDigito;
    return coincideBusqueda && coincideHoy && coincidePendientes && coincideEstado && coincideDomicilio && coincideDigito;
  });
  const empresasConNovedadesHoy = empresas.filter((e) => e.mensajes_hoy > 0).length;
  const empresasConPendientes = empresas.filter((e) => e.pendientes > 0).length;

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 pb-8 pt-24 xl:px-12">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-ink">Empresas</h1>
            <p className="mt-1 text-sm text-slate-600">Empresas que estas monitoreando</p>
          </div>

          <div className="flex flex-wrap gap-2">
            <BotonConsultarTodas
              onClick={consultarTodas}
              consultando={consultandoTodas}
              estado={estadoMasiva}
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
            onCreada={(opts) => {
              if (!opts?.mantenerAbierto) setMostrarForm(false);
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

              <button
                onClick={() => setSoloPendientes((v) => !v)}
                className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-3.5 py-2.5 text-sm font-medium transition-all duration-300 ease-out ${
                  soloPendientes
                    ? "border-accent bg-accent text-white"
                    : "border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50"
                }`}
              >
                <Inbox size={15} strokeWidth={1.5} />
                Con pendientes por leer
                {empresasConPendientes > 0 && (
                  <span
                    className={`rounded-full px-1.5 text-xs ${
                      soloPendientes ? "bg-white/20" : "bg-accent-light text-accent"
                    }`}
                  >
                    {empresasConPendientes}
                  </span>
                )}
              </button>

              {/* Opciones armadas de los valores que de verdad aparecen en tus
                  empresas (no una lista fija) -- asi el filtro nunca queda
                  vacio por una diferencia de texto entre como SUNAT lo
                  escribe realmente y como se nombra "oficialmente". */}
              <select
                value={filtroEstadoContribuyente}
                onChange={(e) => setFiltroEstadoContribuyente(e.target.value)}
                title="Filtrar por Estado del Contribuyente"
                className="shrink-0 rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-slate-600 outline-none focus:border-accent"
              >
                <option value="">Estado: todos</option>
                {opcionesEstadoContribuyente.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>

              <select
                value={filtroCondicionDomicilio}
                onChange={(e) => setFiltroCondicionDomicilio(e.target.value)}
                title="Filtrar por Condicion de Domicilio"
                className="shrink-0 rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-slate-600 outline-none focus:border-accent"
              >
                <option value="">Domicilio: todos</option>
                {opcionesCondicionDomicilio.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>

              <select
                value={filtroUltimoDigito}
                onChange={(e) => setFiltroUltimoDigito(e.target.value)}
                title="Filtrar por ultimo digito del RUC"
                className="shrink-0 rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-slate-600 outline-none focus:border-accent"
              >
                <option value="">Ultimo digito: todos</option>
                {opcionesUltimoDigito.map((d) => (
                  <option key={d} value={d}>
                    Termina en {d}
                  </option>
                ))}
              </select>
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
                    onVerFichaRuc={() => pedirTipoFichaRuc(e, false)}
                    onRegenerarFichaRuc={() => pedirTipoFichaRuc(e, true)}
                    solicitandoReporte={!!solicitandoReporte[e.id]}
                    progresoReporte={progresoReporte[e.id]}
                    onSolicitarReporteTributario={() => pedirReporteTributario(e)}
                    entrandoDirecto={!!entrandoDirecto[e.id]}
                    onEntrarDirecto={() => entrarDirectoASunat(e.id)}
                    entrandoDeclaraciones={!!entrandoDeclaraciones[e.id]}
                    onEntrarDeclaraciones={() => entrarDirectoADeclaraciones(e.id)}
                    entrandoRentaAnual={!!entrandoRentaAnual[e.id]}
                    onEntrarRentaAnual={() => entrarDirectoARentaAnual(e.id)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </main>

      {resultadoConsulta && (
        <InfoDialog
          titulo={resultadoConsulta.titulo}
          mensaje={resultadoConsulta.mensaje}
          variante={resultadoConsulta.variante}
          onCerrar={() => setResultadoConsulta(null)}
        />
      )}
      {pdfRapido && <ModalPdfRapido info={pdfRapido} onClose={() => setPdfRapido(null)} />}
      {eligiendoTipoFicha && (
        <ModalElegirTipoFichaRuc
          info={eligiendoTipoFicha}
          onCancelar={() => setEligiendoTipoFicha(null)}
          onElegir={(conQr) => {
            const { empresa, forzarRegenerar } = eligiendoTipoFicha;
            setEligiendoTipoFicha(null);
            verFichaRuc(empresa, forzarRegenerar, conQr);
          }}
        />
      )}
      {pidiendoReporteTributario && (
        <ModalReporteTributario
          info={pidiendoReporteTributario}
          onIniciarSesion={(nombreVentana) => entrarDirectoASunat(pidiendoReporteTributario.empresa.id, nombreVentana)}
          onCerrar={() => setPidiendoReporteTributario(null)}
        />
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
  solicitandoReporte,
  progresoReporte,
  onSolicitarReporteTributario,
  entrandoDirecto,
  onEntrarDirecto,
  entrandoDeclaraciones,
  onEntrarDeclaraciones,
  entrandoRentaAnual,
  onEntrarRentaAnual,
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
                title={
                  esTipoSevero(e.tipo_hoy_mas_severo)
                    ? `${e.mensajes_hoy} de hoy -- incluye ${e.tipo_hoy_mas_severo}`
                    : `${e.mensajes_hoy} mensaje(s) de hoy`
                }
                className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold transition-colors duration-300 ease-out ${
                  esTipoSevero(e.tipo_hoy_mas_severo)
                    ? colorBadgeTipo(e.tipo_hoy_mas_severo)
                    : "bg-accent-light text-accent hover:bg-blue-100"
                }`}
              >
                {esTipoSevero(e.tipo_hoy_mas_severo) ? (
                  <AlertTriangle size={10} strokeWidth={1.5} />
                ) : (
                  <Sparkles size={10} strokeWidth={1.5} />
                )}
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
          title={
            e.pendientes === 0
              ? "Sin pendientes"
              : esTipoSevero(e.tipo_pendiente_mas_severo)
              ? `${e.pendientes} pendiente(s) -- incluye ${e.tipo_pendiente_mas_severo}`
              : `${e.pendientes} mensaje(s) pendiente(s)`
          }
          className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-bold transition-all duration-300 ease-out hover:-translate-y-0.5 ${
            e.pendientes > 0 ? colorBadgeTipo(e.tipo_pendiente_mas_severo) : "bg-slate-50 text-slate-500"
          }`}
        >
          {esTipoSevero(e.tipo_pendiente_mas_severo) ? (
            <AlertTriangle size={13} strokeWidth={2} />
          ) : (
            <Inbox size={13} strokeWidth={2} />
          )}
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
          onClick={onEntrarDeclaraciones}
          disabled={entrandoDeclaraciones}
          title="Entra directo a Mis Declaraciones y Pagos de SUNAT, ya logueado, sin escribir nada."
          className="inline-flex items-center gap-1.5 rounded-lg bg-sky-50 px-2.5 py-1.5 text-xs font-bold text-sky-700 transition-all duration-300 ease-out hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
        >
          {entrandoDeclaraciones ? (
            <Loader2 size={13} strokeWidth={2} className="animate-spin" />
          ) : (
            <LogIn size={13} strokeWidth={2} />
          )}
          {entrandoDeclaraciones ? "Entrando..." : "Ir a Declaraciones y Pagos"}
        </button>

        <button
          onClick={onEntrarRentaAnual}
          disabled={entrandoRentaAnual}
          title="Entra directo a DJ Anual (Declaracion Jurada Anual de Renta) de SUNAT, ya logueado, sin escribir nada."
          className="inline-flex items-center gap-1.5 rounded-lg bg-violet-50 px-2.5 py-1.5 text-xs font-bold text-violet-700 transition-all duration-300 ease-out hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
        >
          {entrandoRentaAnual ? (
            <Loader2 size={13} strokeWidth={2} className="animate-spin" />
          ) : (
            <LogIn size={13} strokeWidth={2} />
          )}
          {entrandoRentaAnual ? "Entrando..." : "DJ Anual"}
        </button>

        <button
          onClick={onVerFichaRuc}
          disabled={generandoFicha}
          title={
            e.ficha_ruc_generada_en
              ? "Descarga el PDF de la Ficha RUC ya generado"
              : "Genera y descarga el PDF de la Ficha RUC entrando en vivo a SUNAT"
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
            ? "Descargar Ficha"
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

        <button
          onClick={onSolicitarReporteTributario}
          disabled={solicitandoReporte}
          title="Abre en SUNAT el formulario del Reporte Tributario para Terceros (informacion reservada) para que lo envies por correo"
          className="inline-flex items-center gap-1.5 rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs font-bold text-amber-700 transition-all duration-300 ease-out hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:hover:translate-y-0"
        >
          {solicitandoReporte ? (
            <Loader2 size={13} strokeWidth={2} className="animate-spin" />
          ) : (
            <Mail size={13} strokeWidth={2} />
          )}
          {solicitandoReporte
            ? `${infoEtapaReporteTributario(progresoReporte?.etapa).porcentaje}%`
            : "Reporte Tributario"}
        </button>
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

function ModalElegirTipoFichaRuc({ info, onCancelar, onElegir }) {
  const [limite, setLimite] = useState(null); // {usados_hoy, limite} | null
  const [cargandoLimite, setCargandoLimite] = useState(true);

  useEffect(() => {
    let cancelado = false;
    api
      .obtenerLimiteQrFichaRuc(info.empresa.id)
      .then((data) => {
        if (!cancelado) setLimite(data);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelado) setCargandoLimite(false);
      });
    return () => {
      cancelado = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [info.empresa.id]);

  const limiteAlcanzado = limite && limite.usados_hoy >= limite.limite;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-6" onClick={onCancelar}>
      <div
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-soft-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-bold text-ink">Ficha RUC de {info.empresa.razon_social}</h3>
        <p className="mt-2 text-sm text-slate-600">
          Quieres la version con codigo QR de verificacion (Reporte de Ficha RUC, firmado por SUNAT), o la version
          normal (Constancia de Informacion Registrada)?
        </p>
        <p className="mt-2 text-xs text-slate-400">
          {cargandoLimite
            ? "Consultando cuantas veces se genero hoy..."
            : limite
            ? `SUNAT permite generar la version con QR solo ${limite.limite} veces al dia por empresa -- ya usaste ${limite.usados_hoy} de ${limite.limite} hoy.`
            : "SUNAT permite generar la version con QR solo 3 veces al dia por empresa."}
        </p>
        <div className="mt-5 flex flex-col gap-2">
          <button
            onClick={() => onElegir(true)}
            disabled={cargandoLimite}
            title={limiteAlcanzado ? "Ya usaste el limite de hoy -- SUNAT devolvera el ultimo reporte con QR ya generado" : undefined}
            className="flex items-center justify-center gap-1.5 rounded-lg bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
          >
            Si, con codigo QR{limiteAlcanzado ? " (limite del dia alcanzado)" : ""}
          </button>
          <button
            onClick={() => onElegir(false)}
            className="flex items-center justify-center gap-1.5 rounded-lg border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 transition-all duration-300 ease-out hover:border-violet-300 hover:text-violet-700"
          >
            No, la version normal
          </button>
          <button
            onClick={onCancelar}
            className="mt-1 flex items-center justify-center rounded-lg px-4 py-2 text-xs font-medium text-slate-400 transition-colors duration-300 ease-out hover:text-slate-600"
          >
            Cancelar
          </button>
        </div>
      </div>
    </div>
  );
}

// SUNAT exige desde octubre 2026 una verificacion humana (Cloudflare
// Turnstile) para enviar el Reporte Tributario, asi que ya no lo manda el
// robot: se abre en el navegador del propio usuario con UN solo boton --
// 1) el ingreso directo de siempre inicia la sesion en una pestana y 2) en
// cuanto esa pestana llega al Menu SOL, se la manda a este enlace, que con la
// sesion abierta lleva derecho al formulario (probado 20/10/2026). El enlace
// no puede ir como destino del propio login: SUNAT le pega "?state=" y lo rompe.
//
// Como se sabe que ya llego al Menu SOL sin poder leer una pagina de otro
// dominio: el navegador SI deja leer cuantos marcos (iframes) tiene la
// pestana -- el login de SUNAT tiene 0 y el Menu SOL 3 (medido en vivo
// 20/10/2026). Si SUNAT cambia eso, a los 2 minutos se ofrece el boton manual.
const VENTANA_REPORTE_TRIBUTARIO = "sunat_reporte_tributario";
const URL_REPORTE_TRIBUTARIO_SUNAT =
  "https://e-menu.sunat.gob.pe/cl-ti-itmenu/MenuInternet.htm?action=execute&code=10.11.1.1.1&s=ww1";
const MARCOS_MENU_SOL = 3;
const ESPERA_MAXIMA_MENU_SOL_SEG = 120;

function ModalReporteTributario({ info, onIniciarSesion, onCerrar }) {
  // inicio -> entrando -> listo | manual (no se detecto el Menu SOL a tiempo) | cerrada (cerraron la pestana)
  const [paso, setPaso] = useState("inicio");
  const pestanaRef = useRef(null);

  useEffect(() => {
    if (paso !== "entrando") return;
    const inicio = Date.now();
    let vecesEnMenu = 0;
    const t = setInterval(() => {
      const pestana = pestanaRef.current;
      if (!pestana || pestana.closed) {
        clearInterval(t);
        setPaso("cerrada");
        return;
      }
      let marcos = 0;
      try {
        marcos = pestana.length;
      } catch {}
      vecesEnMenu = marcos >= MARCOS_MENU_SOL ? vecesEnMenu + 1 : 0;
      if (vecesEnMenu >= 2) {
        clearInterval(t);
        pestana.location.href = URL_REPORTE_TRIBUTARIO_SUNAT;
        setPaso("listo");
      } else if (Date.now() - inicio > ESPERA_MAXIMA_MENU_SOL_SEG * 1000) {
        clearInterval(t);
        setPaso("manual");
      }
    }, 1000);
    return () => clearInterval(t);
  }, [paso]);

  async function abrirEnSunat() {
    setPaso("entrando");
    const pestana = await onIniciarSesion(VENTANA_REPORTE_TRIBUTARIO);
    if (!pestana) {
      setPaso("inicio");
      return;
    }
    pestanaRef.current = pestana;
  }

  function abrirFormularioManual() {
    pestanaRef.current = window.open(URL_REPORTE_TRIBUTARIO_SUNAT, VENTANA_REPORTE_TRIBUTARIO);
    setPaso("listo");
  }

  const botonPrincipal =
    "flex w-full items-center justify-center gap-1.5 rounded-lg bg-amber-600 px-4 py-2.5 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-amber-700";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-6" onClick={onCerrar}>
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-soft-lg" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-base font-bold text-ink">Reporte Tributario para Terceros</h3>
        <p className="text-xs text-slate-500">{info.empresa.razon_social}</p>

        {paso === "inicio" && (
          <>
            <p className="mt-4 text-sm text-slate-600">
              SUNAT pide comprobar que eres una persona para enviar este reporte, asi que el envio lo haces tu. Nosotros
              entramos a SUNAT por ti y te dejamos en el formulario.
            </p>
            <button type="button" onClick={abrirEnSunat} className={`mt-4 ${botonPrincipal}`}>
              <Mail size={15} strokeWidth={2} />
              Abrir el Reporte Tributario en SUNAT
            </button>
          </>
        )}

        {paso === "entrando" && (
          <div className="mt-5 flex items-start gap-3 rounded-lg bg-slate-50 p-4">
            <Loader2 size={18} strokeWidth={2} className="mt-0.5 shrink-0 animate-spin text-accent" />
            <div className="text-sm text-slate-600">
              <p className="font-semibold text-ink">Entrando a SUNAT en otra pestana...</p>
              <p className="mt-1">
                Tarda entre 10 y 40 segundos. Apenas cargue el Menu SOL, esa pestana pasara sola al formulario del
                Reporte Tributario. Si SUNAT te pregunta por el codigo de seguridad, elige "Continuar sin codigo".
              </p>
            </div>
          </div>
        )}

        {paso === "listo" && (
          <div className="mt-5 rounded-lg border border-emerald-100 bg-emerald-50 p-4 text-sm text-emerald-900">
            <p className="flex items-center gap-1.5 font-semibold">
              <CheckCheck size={16} strokeWidth={2} />
              Listo: ve a la pestana de SUNAT y completa ahi
            </p>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-emerald-800">
              <li>Marca la casilla "Acepto".</li>
              <li>Escribe el correo al que quieres recibir el reporte.</li>
              <li>Completa la verificacion "Verify you are human".</li>
              <li>Presiona "Enviar".</li>
            </ol>
            <button type="button" onClick={abrirFormularioManual} className="mt-3 text-xs font-medium text-emerald-700 underline">
              No veo el formulario -- abrirlo otra vez
            </button>
          </div>
        )}

        {(paso === "manual" || paso === "cerrada") && (
          <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <p>
              {paso === "cerrada"
                ? "Se cerro la pestana de SUNAT antes de llegar al formulario."
                : "SUNAT esta tardando mas de lo normal. Cuando en la otra pestana ya veas el Menu SOL, presiona:"}
            </p>
            {paso === "cerrada" ? (
              <button type="button" onClick={() => setPaso("inicio")} className={`mt-3 ${botonPrincipal}`}>
                Intentar de nuevo
              </button>
            ) : (
              <button type="button" onClick={abrirFormularioManual} className={`mt-3 ${botonPrincipal}`}>
                Ya veo el Menu SOL -- abrir el formulario
              </button>
            )}
          </div>
        )}

        <p className="mt-4 text-xs text-slate-500">
          Informacion reservada (Art. 85 del Codigo Tributario). SUNAT permite 3 reportes por dia; se envia el ultimo
          generado.
        </p>

        <button
          type="button"
          onClick={onCerrar}
          className="mt-3 flex w-full items-center justify-center rounded-lg px-4 py-2 text-xs font-medium text-slate-400 transition-colors duration-300 ease-out hover:text-slate-600"
        >
          Cerrar
        </button>
      </div>
    </div>
  );
}

// Mismo texto exacto que arma adapter.py cuando SUNAT no acepta el
// usuario/clave (ver core_scraper/adapter.py) -- se usa para distinguir
// "credenciales rechazadas" de cualquier otro motivo de fallo (portal
// caido, timeout, etc.), que no ameritan pedirle al usuario que las
// corrija.
const ERROR_CREDENCIALES_INCORRECTAS = "revisa usuario/clave";
// Cuantas veces (cada 3s, ~90s en total) esperar a que la consulta
// automatica de la empresa recien creada termine antes de dejar de
// bloquear el formulario -- una consulta normal rara vez tarda mas que
// esto, y si tarda mas el usuario igual puede seguir usando el sistema
// mientras termina en segundo plano.
const INTENTOS_VERIFICAR_CREDENCIALES = 30;

function FormularioEmpresa({ onCreada }) {
  const [ruc, setRuc] = useState("");
  const [razonSocial, setRazonSocial] = useState("");
  const [usuarioSol, setUsuarioSol] = useState("");
  const [claveSol, setClaveSol] = useState("");
  const [claveSolRepetir, setClaveSolRepetir] = useState("");
  const [obligacionIgvRenta, setObligacionIgvRenta] = useState(true);
  const [obligacionPlame, setObligacionPlame] = useState(false);
  const [obligacionSbs, setObligacionSbs] = useState(false);
  const [obligacionCts, setObligacionCts] = useState(false);
  const [obligacionItan, setObligacionItan] = useState(false);
  const [obligacionSire, setObligacionSire] = useState(false);
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [verificando, setVerificando] = useState(false);
  const [avisoCredenciales, setAvisoCredenciales] = useState(null); // { empresaId, razonSocial, detalle, esCredencialesIncorrectas } | null
  const [mostrarConfirmarEliminarConError, setMostrarConfirmarEliminarConError] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setAvisoCredenciales(null);
    if (claveSol !== claveSolRepetir) {
      setError("La clave SOL y su repeticion no coinciden.");
      return;
    }
    setGuardando(true);
    try {
      const empresaCreada = await api.crearEmpresa({
        ruc,
        razon_social: razonSocial,
        usuario_sol: usuarioSol,
        clave_sol: claveSol,
        obligacion_igv_renta: obligacionIgvRenta,
        obligacion_plame: obligacionPlame,
        obligacion_sbs: obligacionSbs,
        obligacion_cts: obligacionCts,
        obligacion_itan: obligacionItan,
        obligacion_sire: obligacionSire,
      });
      setGuardando(false);
      await verificarCredencialesRecienCreadas(empresaCreada);
    } catch (err) {
      setError(err.message);
      setGuardando(false);
    }
  }

  async function verificarCredencialesRecienCreadas(empresaCreada) {
    setVerificando(true);
    for (let intento = 0; intento < INTENTOS_VERIFICAR_CREDENCIALES; intento++) {
      await new Promise((resolver) => setTimeout(resolver, 3000));
      let jobs;
      try {
        jobs = await api.listarJobsDeEmpresa(empresaCreada.id);
      } catch {
        break; // si falla el propio polling, no trabar al usuario -- se vera igual en la lista
      }
      const job = jobs[0]; // el mas reciente, el backend ya ordena desc
      if (!job) break; // no se llego a encolar nada (caso raro, ej. limite por RUC) -- no bloquear
      if (job.estado === "completado") {
        setVerificando(false);
        onCreada();
        return;
      }
      if (job.estado === "error") {
        setVerificando(false);
        setAvisoCredenciales({
          empresaId: empresaCreada.id,
          razonSocial: empresaCreada.razon_social,
          detalle: job.error,
          esCredencialesIncorrectas: (job.error || "").includes(ERROR_CREDENCIALES_INCORRECTAS),
        });
        onCreada({ mantenerAbierto: true }); // la empresa ya quedo creada -- refrescar la lista sin cerrar el formulario
        return;
      }
      // pendiente o en_progreso -> seguir esperando
    }
    // se agoto la espera sin resultado definitivo: no bloquear mas, la
    // consulta sigue en curso en segundo plano y se vera en la lista.
    setVerificando(false);
    onCreada();
  }

  async function confirmarEliminarEmpresaConError() {
    setMostrarConfirmarEliminarConError(false);
    if (!avisoCredenciales) return;
    try {
      await api.eliminarEmpresa(avisoCredenciales.empresaId);
      setAvisoCredenciales(null);
    } catch (err) {
      alert(err.message);
    }
  }

  return (
    <>
    <form onSubmit={onSubmit} className="surface-card mt-6 animate-fade-in-up p-6">
      {error && (
        <div className="mb-4 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
      )}
      {verificando && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-accent-light bg-accent-light/40 px-3 py-2.5 text-sm text-accent">
          <Loader2 size={14} strokeWidth={1.5} className="animate-spin" />
          Verificando el usuario y clave SOL con SUNAT...
        </div>
      )}
      {avisoCredenciales && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-700">
          <div className="flex items-start gap-2">
            <AlertTriangle size={16} strokeWidth={1.5} className="mt-0.5 shrink-0" />
            <p>
              {avisoCredenciales.esCredencialesIncorrectas ? (
                <>
                  <strong>{avisoCredenciales.razonSocial}</strong> se guardo, pero SUNAT rechazo el usuario/clave SOL
                  ingresados. Corrigelos para que las consultas funcionen.
                </>
              ) : (
                <>
                  <strong>{avisoCredenciales.razonSocial}</strong> se guardo, pero la primera consulta fallo:{" "}
                  {avisoCredenciales.detalle}. Puede ser algo temporal de SUNAT -- prueba "Consultar" de nuevo en un
                  momento.
                </>
              )}
            </p>
          </div>
          <div className="mt-2 flex gap-4 pl-6">
            <Link href={`/empresas/${avisoCredenciales.empresaId}`} className="font-medium underline">
              Ir a corregir credenciales
            </Link>
            <button type="button" onClick={() => setMostrarConfirmarEliminarConError(true)} className="font-medium underline">
              Eliminar empresa
            </button>
          </div>
        </div>
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
        <Campo id="claveSolRepetir" label="Repetir clave SOL">
          <input
            id="claveSolRepetir"
            type="password"
            value={claveSolRepetir}
            onChange={(e) => setClaveSolRepetir(e.target.value)}
            required
            className="campo-input"
          />
        </Campo>
      </div>

      <div className="mt-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
          Obligaciones recurrentes de esta empresa
        </p>
        <div className="flex flex-wrap gap-4">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={obligacionIgvRenta}
              onChange={(e) => setObligacionIgvRenta(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            IGV-Renta mensual
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={obligacionPlame}
              onChange={(e) => setObligacionPlame(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            PLAME (Planilla y AFP)
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={obligacionSbs}
              onChange={(e) => setObligacionSbs(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            Reporte de Operaciones SBS
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={obligacionCts}
              onChange={(e) => setObligacionCts(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            CTS (deposito semestral, Mayo y Noviembre)
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={obligacionItan}
              onChange={(e) => setObligacionItan(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            ITAN (recordatorio anual, Abril)
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={obligacionSire}
              onChange={(e) => setObligacionSire(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            SIRE (Registro de Compras/Ventas Electronico)
          </label>
        </div>
        <p className="mt-1.5 text-xs text-slate-400">
          Las que marques generan tareas automaticamente cada mes (o en los meses que corresponda) en el modulo
          Tareas -- puedes ajustarlas despues desde el detalle de la empresa, incluyendo la periodicidad exacta
          (mensual, cada cierto numero de meses, o meses especificos).
        </p>
      </div>

      <button
        type="submit"
        disabled={guardando || verificando}
        className="mt-5 flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
      >
        {(guardando || verificando) && <Loader2 size={14} strokeWidth={1.5} className="animate-spin" />}
        {guardando ? "Guardando..." : verificando ? "Verificando..." : "Guardar empresa"}
      </button>
    </form>

    {mostrarConfirmarEliminarConError && avisoCredenciales && (
      <ConfirmDialog
        titulo={`Eliminar "${avisoCredenciales.razonSocial}"?`}
        mensaje="Se borraran tambien sus mensajes. Esto no se puede deshacer."
        textoConfirmar="Si, eliminar"
        peligroso
        onConfirmar={confirmarEliminarEmpresaConError}
        onCancelar={() => setMostrarConfirmarEliminarConError(false)}
      />
    )}
    </>
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
      <p className="mt-2 text-xs text-slate-400">
        Opcional: agrega columnas "IGV-Renta", "PLAME", "SBS", "CTS", "ITAN" y/o "SIRE" con Si/No para elegir sus
        obligaciones desde el Excel -- si no las incluyes, cada empresa se crea con IGV-Renta activado (el resto
        sin marcar), igual que en el formulario manual.
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
