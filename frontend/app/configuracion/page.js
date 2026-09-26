"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Settings, Loader2, CheckCircle2 } from "lucide-react";
import Sidebar from "../../components/Sidebar";
import { api, getToken } from "../../lib/api";

const CAMPOS = [
  {
    clave: "limite_mensajes_por_consulta",
    etiqueta: "Limite de mensajes por consulta",
    ayuda: "Cuantos mensajes del Buzon de Notificaciones lee como maximo cada consulta a una empresa.",
    min: 1,
    max: 200,
  },
  {
    clave: "espaciado_seg_entre_consultas",
    etiqueta: "Espaciado entre consultas (segundos)",
    ayuda: 'Tiempo entre cada empresa de una tanda -- chequeo nocturno, "Consultar todas" e importacion masiva.',
    min: 5,
    max: 600,
  },
  {
    clave: "concurrencia_maxima",
    etiqueta: "Concurrencia maxima",
    ayuda: "Cuantas sesiones de SUNAT pueden correr en paralelo en todo el sistema, sin importar cuantos workers haya.",
    min: 1,
    max: 20,
  },
  {
    clave: "segundos_entre_consultas_mismo_ruc",
    etiqueta: "Minimo entre consultas del mismo RUC (segundos)",
    ayuda: "Evita que una misma empresa se consulte dos veces demasiado seguido.",
    min: 5,
    max: 3600,
  },
];

// Peru esta en UTC-5 todo el ano (sin horario de verano), asi que la
// conversion es una resta fija -- no hace falta ninguna libreria de zonas
// horarias para mostrar el equivalente al lado del campo en UTC.
function horaPeru(horaUtc, minutoUtc) {
  const hora = (Number(horaUtc) + 19) % 24; // (horaUtc - 5 + 24) % 24
  return `${String(hora).padStart(2, "0")}:${String(Number(minutoUtc) || 0).padStart(2, "0")}`;
}

const CHEQUEOS = [
  { id: 1, horaClave: "chequeo1_hora", minutoClave: "chequeo1_minuto", etiqueta: "Chequeo 1" },
  { id: 2, horaClave: "chequeo2_hora", minutoClave: "chequeo2_minuto", etiqueta: "Chequeo 2" },
];

export default function ConfiguracionPage() {
  const router = useRouter();
  const [valores, setValores] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const [guardado, setGuardado] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api
      .obtenerConfiguracionSistema()
      .then(setValores)
      .catch((err) => setError(err.message))
      .finally(() => setCargando(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function cambiarCampo(clave, valor) {
    setGuardado(false);
    setValores((prev) => ({ ...prev, [clave]: valor }));
  }

  async function guardar(e) {
    e.preventDefault();
    setGuardando(true);
    setError("");
    setGuardado(false);
    try {
      const clavesHorario = CHEQUEOS.flatMap(({ horaClave, minutoClave }) => [horaClave, minutoClave]);
      const payload = Object.fromEntries(
        [...CAMPOS.map(({ clave }) => clave), ...clavesHorario].map((clave) => [clave, Number(valores[clave])])
      );
      const actualizado = await api.actualizarConfiguracionSistema(payload);
      setValores(actualizado);
      setGuardado(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 pb-8 pt-24 xl:px-12">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-light text-accent">
            <Settings size={18} strokeWidth={1.5} />
          </div>
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-ink">Panel maestro</h1>
            <p className="mt-0.5 text-sm text-slate-600">
              Ajustes operativos globales -- afectan a todos los tenants, no solo al tuyo. Solo visible para el equipo
              de la plataforma.
            </p>
          </div>
        </div>

        {error && (
          <div className="mt-6 max-w-lg rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">
            {error}
          </div>
        )}

        {cargando || !valores ? (
          <p className="mt-8 text-sm text-slate-500">Cargando...</p>
        ) : (
          <form onSubmit={guardar} className="surface-card mt-6 max-w-lg space-y-5 p-6">
            {CAMPOS.map(({ clave, etiqueta, ayuda, min, max }) => (
              <div key={clave}>
                <label htmlFor={clave} className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
                  {etiqueta}
                </label>
                <input
                  id={clave}
                  type="number"
                  min={min}
                  max={max}
                  required
                  value={valores[clave]}
                  onChange={(e) => cambiarCampo(clave, e.target.value)}
                  className="campo-input w-40"
                />
                <p className="mt-1 text-xs text-slate-500">{ayuda}</p>
              </div>
            ))}

            <div className="border-t border-slate-100 pt-5">
              <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">
                Horario de consulta masiva automatica (hora UTC del servidor)
              </p>
              <p className="mb-3 text-xs text-slate-500">
                Dos chequeos automaticos al dia recorren todas las empresas activas de todos los tenants. El cambio
                aplica solo con "Guardar cambios", sin redeploy (hasta 5 minutos de demora en tomar efecto).
              </p>
              <div className="space-y-4">
                {CHEQUEOS.map(({ id, horaClave, minutoClave, etiqueta }) => (
                  <div key={id} className="flex flex-wrap items-end gap-3">
                    <span className="w-20 text-sm font-medium text-ink">{etiqueta}</span>
                    <div>
                      <label htmlFor={horaClave} className="mb-1 block text-[11px] text-slate-500">
                        Hora (0-23)
                      </label>
                      <input
                        id={horaClave}
                        type="number"
                        min={0}
                        max={23}
                        required
                        value={valores[horaClave]}
                        onChange={(e) => cambiarCampo(horaClave, e.target.value)}
                        className="campo-input w-20"
                      />
                    </div>
                    <div>
                      <label htmlFor={minutoClave} className="mb-1 block text-[11px] text-slate-500">
                        Minuto (0-59)
                      </label>
                      <input
                        id={minutoClave}
                        type="number"
                        min={0}
                        max={59}
                        required
                        value={valores[minutoClave]}
                        onChange={(e) => cambiarCampo(minutoClave, e.target.value)}
                        className="campo-input w-20"
                      />
                    </div>
                    <span className="pb-2.5 text-xs text-slate-500">
                      = {horaPeru(valores[horaClave], valores[minutoClave])} hora Peru
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-3 border-t border-slate-100 pt-5">
              <button
                type="submit"
                disabled={guardando}
                className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
              >
                {guardando && <Loader2 size={15} strokeWidth={2} className="animate-spin" />}
                Guardar cambios
              </button>
              {guardado && (
                <span className="flex items-center gap-1 text-sm font-medium text-emerald-600">
                  <CheckCircle2 size={15} strokeWidth={1.75} />
                  Guardado
                </span>
              )}
            </div>
          </form>
        )}
      </main>
    </div>
  );
}
