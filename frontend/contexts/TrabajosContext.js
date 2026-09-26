"use client";
// Registro global de trabajos en curso (consulta al buzon, Ficha RUC,
// Reporte Tributario). Antes este progreso vivia en el estado local de
// /empresas (useState) y desaparecia en cuanto el usuario navegaba a otra
// pantalla -- el job seguia corriendo en el servidor, pero la unica senal
// visual se perdia y el usuario no sabia si su solicitud seguia en pie
// (reportado en produccion, 25/09). Este Provider vive en app/layout.js,
// que Next.js NUNCA desmonta durante la navegacion entre paginas -- el
// polling y su resultado sobreviven el cambio de pantalla.
import { createContext, useCallback, useContext, useRef, useState } from "react";
import { api } from "../lib/api";

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
    <TrabajosContext.Provider value={{ trabajos, trabajosActivos, iniciarTrabajo, quitar }}>
      {children}
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
