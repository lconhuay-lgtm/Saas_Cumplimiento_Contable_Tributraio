"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "../../../../lib/api";

// Las lecturas de SUNAT del periodo (Bloque 1): las usan el boton "Actualizar
// ahora" del encabezado del tablero y el bloque "Datos de SUNAT". Mientras hay
// una lectura en curso se refresca sola; al terminar avisa con onLeido para
// que el tablero recalcule.
const SEGUNDOS_REFRESCO = 6;

export default function useLecturas(empresaId, periodo, onLeido) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [pidiendo, setPidiendo] = useState(false);
  const enCursoAntes = useRef(false);

  async function cargar() {
    try {
      setDatos(await api.verLecturasLiquidacion(empresaId, periodo));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    setDatos(null);
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empresaId, periodo]);

  useEffect(() => {
    if (!datos?.en_curso) return undefined;
    const reloj = setInterval(cargar, SEGUNDOS_REFRESCO * 1000);
    return () => clearInterval(reloj);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datos?.en_curso, empresaId, periodo]);

  useEffect(() => {
    if (enCursoAntes.current && datos && !datos.en_curso) onLeido?.();
    enCursoAntes.current = Boolean(datos?.en_curso);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datos?.en_curso]);

  async function leer() {
    setPidiendo(true);
    setError("");
    try {
      setDatos(await api.pedirLecturasLiquidacion(empresaId, periodo));
    } catch (err) {
      setError(err.message);
    } finally {
      setPidiendo(false);
    }
  }

  return { datos, error, pidiendo, leer };
}
