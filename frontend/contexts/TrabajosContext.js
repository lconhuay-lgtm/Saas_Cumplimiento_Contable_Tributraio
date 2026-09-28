"use client";
// Registro global de trabajos en curso (consulta al buzon, Ficha RUC,
// Reporte Tributario). Antes este progreso vivia en el estado local de
// /empresas (useState) y desaparecia en cuanto el usuario navegaba a otra
// pantalla -- el job seguia corriendo en el servidor, pero la unica senal
// visual se perdia y el usuario no sabia si su solicitud seguia en pie
// (reportado en produccion, 25/09). Este Provider vive en app/layout.js,
// que Next.js NUNCA desmonta durante la navegacion entre paginas -- el
// polling y su resultado sobreviven el cambio de pantalla.
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, getToken } from "../lib/api";
import { formatoResumenFinal } from "../components/BotonConsultarTodas";
import InfoDialog from "../components/InfoDialog";

const TrabajosContext = createContext(null);

function clave(tipo, empresaId) {
  return `${tipo}:${empresaId}`;
}

// Mismo endpoint de jobs, distinto shape de URL por tipo (ver lib/api.js).
const CONSULTAR_JOB = {
  consulta: (empresaId, jobId) => api.obtenerJob(jobId),
  ficha: (empresaId, jobId) => api.obtenerJobFichaRuc(empresaId, jobId),
  reporte: (empresaId, jobId) => api.obtenerJobReporteTributario(empresaId, jobId),
};

export function TrabajosProvider({ children }) {
  const [trabajos, setTrabajos] = useState({});
  // Evita arrancar dos pollers para el mismo trabajo si el usuario dispara
  // la misma accion dos veces seguidas.
  const enCursoRef = useRef({});

  // Seguimiento de la tanda de "Consulta masiva" -- vivia antes como
  // estado local de /empresas y /dashboard (cada una con su propio poll de
  // GET /consultas/estado), asi que apenas el usuario navegaba a OTRA
  // pantalla, o cerraba esa pestana, perdia todo rastro de si la tanda
  // seguia corriendo o ya habia terminado (reportado en produccion, 28/09:
  // "las consultas masivas corren en silencio, se cierran sin saber si ya
  // terminaron"). Se mueve aca, al Provider que vive en app/layout.js y
  // nunca se desmonta, con el mismo criterio que ya se usaba para
  // consulta/ficha/reporte individuales.
  const [estadoMasiva, setEstadoMasiva] = useState(null);
  const [resumenMasivo, setResumenMasivo] = useState(null);
  const masivaEnCursoAnteriorRef = useRef(false);

  useEffect(() => {
    if (!getToken()) return;
    let cancelado = false;
    async function poll() {
      try {
        const data = await api.estadoConsultas();
        if (!cancelado) setEstadoMasiva(data);
      } catch (err) {
        // silencioso -- un poll fallido no debe interrumpir la app
      }
    }
    poll();
    const intervalo = setInterval(poll, 5000);
    return () => {
      cancelado = true;
      clearInterval(intervalo);
    };
  }, []);

  useEffect(() => {
    if (masivaEnCursoAnteriorRef.current && estadoMasiva && !estadoMasiva.en_curso) {
      setResumenMasivo({
        titulo: "Consulta masiva terminada",
        mensaje: formatoResumenFinal(estadoMasiva),
        variante: estadoMasiva.con_error > 0 ? "error" : "ok",
      });
    }
    if (estadoMasiva) masivaEnCursoAnteriorRef.current = estadoMasiva.en_curso;
  }, [estadoMasiva]);

  const actualizar = useCallback((tipo, empresaId, datos) => {
    setTrabajos((prev) => ({ ...prev, [clave(tipo, empresaId)]: { tipo, empresaId, ...datos } }));
  }, []);

  const quitar = useCallback((tipo, empresaId) => {
    setTrabajos((prev) => {
      if (!(clave(tipo, empresaId) in prev)) return prev;
      const copia = { ...prev };
      delete copia[clave(tipo, empresaId)];
      return copia;
    });
  }, []);

  // Polea el job cada 3s (200 intentos = 10 min, igual al job_timeout del
  // servidor) y va guardando la etapa en el estado global. Vive en este
  // Provider -- NO en un useEffect de la pagina que lo dispara -- para que
  // siga corriendo aunque esa pagina se desmonte. Devuelve el job final
  // (completado o error) para que quien llamo pueda seguir mostrando su
  // propio mensaje de resultado.
  const iniciarTrabajo = useCallback(
    async (tipo, empresaId, empresaNombre, jobId) => {
      const k = clave(tipo, empresaId);
      if (enCursoRef.current[k]) return enCursoRef.current[k];
      const consultarJob = CONSULTAR_JOB[tipo];
      const promesa = (async () => {
        actualizar(tipo, empresaId, { empresaNombre, estado: "pendiente", etapa: null });
        try {
          for (let i = 0; i < 200; i++) {
            const job = await consultarJob(empresaId, jobId);
            actualizar(tipo, empresaId, { empresaNombre, estado: job.estado, etapa: job.etapa });
            if (job.estado === "completado" || job.estado === "error") {
              return job;
            }
            await new Promise((resolve) => setTimeout(resolve, 3000));
          }
          throw new Error("Esta tardando mas de lo esperado. Revisa el historial mas tarde.");
        } finally {
          delete enCursoRef.current[k];
        }
      })();
      enCursoRef.current[k] = promesa;
      return promesa;
    },
    [actualizar]
  );

  const trabajosActivos = Object.values(trabajos).filter(
    (t) => t.estado !== "completado" && t.estado !== "error"
  );

  return (
    <TrabajosContext.Provider value={{ trabajos, trabajosActivos, iniciarTrabajo, quitar, estadoMasiva }}>
      {children}
      {/* Vive aca (no en empresas/page.js ni dashboard/page.js) para que se
          vea sin importar en que pantalla este el usuario cuando la tanda
          termina -- ver el comentario de estadoMasiva mas arriba. */}
      {resumenMasivo && (
        <InfoDialog
          titulo={resumenMasivo.titulo}
          mensaje={resumenMasivo.mensaje}
          variante={resumenMasivo.variante}
          onCerrar={() => setResumenMasivo(null)}
        />
      )}
    </TrabajosContext.Provider>
  );
}

export function useTrabajos() {
  const ctx = useContext(TrabajosContext);
  if (!ctx) throw new Error("useTrabajos debe usarse dentro de <TrabajosProvider>");
  return ctx;
}

// Helper para paginas que necesitan el progreso de un solo tipo, con la
// misma forma { [empresaId]: {estado, etapa} } que usaban antes (para no
// tener que reescribir el JSX que ya lee progresoConsulta[e.id], etc).
export function progresoPorTipo(trabajos, tipo) {
  const resultado = {};
  for (const t of Object.values(trabajos)) {
    if (t.tipo === tipo) resultado[t.empresaId] = { estado: t.estado, etapa: t.etapa };
  }
  return resultado;
}
