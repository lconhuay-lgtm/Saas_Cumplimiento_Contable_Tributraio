"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { BookOpen, CheckCircle2, KeyRound, Loader2, PlugZap, Trash2 } from "lucide-react";
import { api } from "../../../lib/api";
import { fechaHoraPeru } from "../../../lib/fechas";
import { ACCIONES_EVENTO, ESTADOS_LIQUIDACION, REGIMENES, textoRegimen } from "../../../lib/liquidacion";
import ConfirmDialog from "../../../components/ConfirmDialog";

// Pestana "Liquidacion en vivo" de cada empresa (Etapa 1): activacion (admin),
// regimen tributario, credenciales de la API del SIRE (solo el responsable)
// y prueba de conexion, con el historial de cambios.
export default function SeccionLiquidacion({ empresaId }) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(null); // "activar" | "guardar" | "probar" | "borrar" | "regimen"
  const [editandoApi, setEditandoApi] = useState(false);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [confirmarBorrar, setConfirmarBorrar] = useState(false);

  useEffect(() => {
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empresaId]);

  async function cargar() {
    try {
      setDatos(await api.obtenerLiquidacionEmpresa(empresaId));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  async function ejecutar(accion, fn) {
    setOcupado(accion);
    setError("");
    try {
      await fn();
      await cargar();
      return true;
    } catch (err) {
      setError(err.message);
      return false;
    } finally {
      setOcupado(null);
    }
  }

  async function guardarApi(e) {
    e.preventDefault();
    const ok = await ejecutar("guardar", () => api.guardarApiSire(empresaId, clientId.trim(), clientSecret.trim()));
    if (ok) {
      setEditandoApi(false);
      setClientId("");
      setClientSecret("");
    }
  }

  if (!datos) {
    return error ? (
      <div className="mt-6 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
    ) : (
      <p className="mt-8 text-sm text-slate-500">Cargando...</p>
    );
  }

  const estado = ESTADOS_LIQUIDACION[datos.estado] || ESTADOS_LIQUIDACION.no_activada;
  const puedeProbar = datos.puede_editar_api || datos.es_admin;
  const tieneApi = datos.api_estado !== "sin_configurar";
  const mostrarFormulario = datos.puede_editar_api && datos.activa && (!tieneApi || editandoApi);
  const caja = "rounded-xl border border-slate-200 bg-white p-5";
  const boton = "flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-bold transition-colors disabled:cursor-not-allowed disabled:opacity-60";

  return (
    <div className="mt-6 grid gap-5 xl:grid-cols-[1.4fr_1fr]">
      <div className="space-y-5">
        {error && <div className="rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>}

        {/* Situacion */}
        <div className={caja}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Situación</div>
              <span className={`mt-1 inline-block rounded-full px-2.5 py-0.5 text-sm font-semibold ${estado.chip}`}>{estado.texto}</span>
            </div>
            {datos.es_admin && (
              <button
                onClick={() => ejecutar("activar", () => api.activarLiquidacion(empresaId, !datos.activa))}
                disabled={!!ocupado}
                className={`${boton} ${datos.activa ? "border border-slate-200 text-slate-600 hover:border-red-300 hover:text-red-600" : "bg-accent text-white hover:opacity-90"}`}
              >
                {ocupado === "activar" && <Loader2 size={14} className="animate-spin" />}
                {datos.activa ? "Desactivar" : "Activar Liquidación en vivo"}
              </button>
            )}
          </div>
          <p className="mt-3 text-sm text-slate-600">{estado.siguiente}</p>
          {datos.responsable_nombre && (
            <p className="mt-1 text-xs text-slate-500">Responsable: {datos.responsable_nombre}</p>
          )}
        </div>

        {/* API del SIRE */}
        <div className={caja}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="flex items-center gap-2 text-base font-bold text-ink">
              <KeyRound size={17} strokeWidth={1.75} className="text-accent" />
              API del SIRE
            </h3>
            <Link href="/liquidacion/guia" target="_blank" className="flex items-center gap-1 text-xs font-semibold text-accent hover:underline">
              <BookOpen size={13} strokeWidth={1.75} />
              Cómo generar las credenciales
            </Link>
          </div>

          {tieneApi && !editandoApi && (
            <div className="mt-3 space-y-2 text-sm text-slate-600">
              <p>
                ID de la API guardado: <span className="font-mono font-semibold text-ink">{datos.api_client_id}</span>
                <span className="text-slate-400"> · la clave se guarda cifrada y no se vuelve a mostrar</span>
              </p>
              {datos.api_mensaje && (
                <p className={datos.api_estado === "ok" ? "text-emerald-700" : datos.api_estado === "error" ? "text-red-600" : ""}>
                  {datos.api_estado === "ok" && <CheckCircle2 size={14} className="mr-1 inline" />}
                  {datos.api_mensaje}
                  {datos.api_probado_en && <span className="text-slate-400"> ({fechaHoraPeru(datos.api_probado_en)})</span>}
                </p>
              )}
            </div>
          )}

          {!datos.puede_editar_api && (
            <p className="mt-3 text-sm text-slate-500">
              {datos.responsable_nombre
                ? `Solo ${datos.responsable_nombre}, responsable de esta empresa, puede guardar o cambiar las credenciales.`
                : "Asigna un responsable en la pestaña Configuración: es el único que puede guardar las credenciales."}
            </p>
          )}

          {datos.puede_editar_api && !datos.activa && (
            <p className="mt-3 text-sm text-slate-500">Las credenciales se pueden guardar cuando un administrador active la empresa.</p>
          )}

          {mostrarFormulario && (
            <form onSubmit={guardarApi} className="mt-4 space-y-3" autoComplete="off">
              <label className="block text-sm font-semibold text-slate-700">
                ID de la API (client_id)
                <input
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  required
                  minLength={8}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm focus:border-accent focus:outline-none"
                />
              </label>
              <label className="block text-sm font-semibold text-slate-700">
                Clave de la API (client_secret)
                <input
                  type="password"
                  value={clientSecret}
                  onChange={(e) => setClientSecret(e.target.value)}
                  required
                  minLength={8}
                  autoComplete="new-password"
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm focus:border-accent focus:outline-none"
                />
              </label>
              <p className="text-xs text-slate-500">
                El usuario y la clave SOL son los que ya están guardados para esta empresa. La clave de la API se guarda cifrada.
              </p>
              <div className="flex gap-2">
                <button type="submit" disabled={!!ocupado} className={`${boton} bg-accent text-white hover:opacity-90`}>
                  {ocupado === "guardar" && <Loader2 size={14} className="animate-spin" />}
                  Guardar credenciales
                </button>
                {editandoApi && (
                  <button type="button" onClick={() => setEditandoApi(false)} className={`${boton} border border-slate-200 text-slate-600`}>
                    Cancelar
                  </button>
                )}
              </div>
            </form>
          )}

          {tieneApi && !editandoApi && (
            <div className="mt-4 flex flex-wrap gap-2">
              {puedeProbar && (
                <button
                  onClick={() => ejecutar("probar", () => api.probarApiSire(empresaId))}
                  disabled={!!ocupado}
                  className={`${boton} bg-accent text-white hover:opacity-90`}
                >
                  {ocupado === "probar" ? <Loader2 size={14} className="animate-spin" /> : <PlugZap size={14} />}
                  {ocupado === "probar" ? "Probando con SUNAT..." : "Probar conexión"}
                </button>
              )}
              {datos.puede_editar_api && (
                <>
                  <button onClick={() => setEditandoApi(true)} disabled={!!ocupado} className={`${boton} border border-slate-200 text-slate-600 hover:border-accent hover:text-accent`}>
                    Cambiar credenciales
                  </button>
                  <button onClick={() => setConfirmarBorrar(true)} disabled={!!ocupado} className={`${boton} border border-slate-200 text-slate-600 hover:border-red-300 hover:text-red-600`}>
                    <Trash2 size={14} />
                    Borrar
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        {/* Regimen */}
        <div className={caja}>
          <h3 className="text-base font-bold text-ink">Régimen tributario</h3>
          <p className="mt-1 text-sm text-slate-600">
            Define la tasa del pago a cuenta de Renta.
            {datos.regimen_sugerido && ` Según sus pagos de Renta en SUNAT: ${textoRegimen(datos.regimen_sugerido)}.`}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <select
              value={datos.regimen || ""}
              disabled={!!ocupado || !(datos.es_admin || datos.puede_editar_api)}
              onChange={(e) => e.target.value && ejecutar("regimen", () => api.cambiarRegimenLiquidacion(empresaId, e.target.value))}
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-accent focus:outline-none disabled:bg-slate-50"
            >
              <option value="">Elegir régimen...</option>
              {REGIMENES.map((r) => (
                <option key={r.id} value={r.id}>{r.texto}</option>
              ))}
            </select>
            {ocupado === "regimen" && <Loader2 size={14} className="animate-spin text-slate-400" />}
            {datos.regimen && (
              <span className="text-xs text-slate-500">
                {datos.regimen_origen === "pagos" ? "Tomado de sus pagos de Renta" : "Elegido a mano"}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Historial */}
      <div className={`${caja} h-fit`}>
        <h3 className="text-base font-bold text-ink">Historial de cambios</h3>
        {datos.eventos.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">Sin cambios todavía.</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {datos.eventos.map((ev, i) => (
              <li key={i} className="text-sm">
                <div className="font-semibold text-ink">{ACCIONES_EVENTO[ev.accion] || ev.accion}</div>
                {ev.detalle && <div className="text-slate-600">{ev.accion === "regimen_cambiado" ? textoRegimen(ev.detalle) : ev.detalle}</div>}
                <div className="text-xs text-slate-400">
                  {ev.usuario_nombre || "Sistema"} · {fechaHoraPeru(ev.creado_en)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {confirmarBorrar && (
        <ConfirmDialog
          titulo="¿Borrar las credenciales de la API?"
          mensaje="La Liquidación en vivo de esta empresa dejará de calcularse hasta que se guarden unas nuevas."
          textoConfirmar="Sí, borrar"
          peligroso
          onConfirmar={async () => {
            setConfirmarBorrar(false);
            await ejecutar("borrar", () => api.borrarApiSire(empresaId));
          }}
          onCancelar={() => setConfirmarBorrar(false)}
        />
      )}
    </div>
  );
}
