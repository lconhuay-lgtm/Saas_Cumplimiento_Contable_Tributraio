"use client";
import { useEffect, useRef, useState } from "react";
import { Check, Copy, Eye, EyeOff, KeyRound, Loader2, Lock, ShieldCheck, Sparkles, X } from "lucide-react";
import { api } from "../lib/api";

// Clave SOL para la PLAME: el programa PLAME de SUNAT pide RUC, usuario y
// clave SOL a mano. Con un PIN de 4 digitos propio, el usuario ve los de la
// empresa y los copia (backend/app/routers/clave_sol.py). Misma ventana para
// el aviso de la novedad, crear el PIN, pedirlo y mostrar los datos.

export const LEYENDA_PLAME =
  "Clave SOL para la PLAME: con tu PIN de 4 digitos ves el RUC, el usuario y la clave SOL de la empresa para copiarlos y pegarlos en el programa PLAME.";

const SEGUNDOS_POR_DEFECTO = 60;

// Boton chico al lado del nombre de la empresa.
export function BotonPlame({ onClick, className = "" }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={LEYENDA_PLAME}
      className={`inline-flex items-center gap-1 rounded-full border border-accent/30 bg-accent-light px-2 py-0.5 text-[10px] font-bold text-accent transition-colors hover:bg-accent hover:text-white ${className}`}
    >
      <KeyRound size={11} strokeWidth={2.25} />
      PLAME
    </button>
  );
}

function CampoPin({ valor, onCambio, autoFocus, etiqueta }) {
  return (
    <label className="block text-xs font-semibold text-slate-500">
      {etiqueta}
      <input
        type="password"
        inputMode="numeric"
        autoComplete="off"
        maxLength={4}
        autoFocus={autoFocus}
        value={valor}
        onChange={(e) => onCambio(e.target.value.replace(/\D/g, "").slice(0, 4))}
        className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-center text-xl font-bold tracking-[0.6em] text-ink focus:border-accent focus:outline-none"
      />
    </label>
  );
}

function FilaDato({ etiqueta, valor, secreto }) {
  const [visible, setVisible] = useState(!secreto);
  const [copiado, setCopiado] = useState(false);

  async function copiar() {
    try {
      await navigator.clipboard.writeText(valor);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 1500);
    } catch {
      setVisible(true); // sin portapapeles, al menos que se pueda leer
    }
  }

  return (
    <div className="flex items-center gap-2 rounded-xl border border-slate-100 px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{etiqueta}</p>
        <p className="truncate font-mono text-sm font-bold text-ink">{visible ? valor : "•".repeat(Math.max(valor.length, 8))}</p>
      </div>
      {secreto && (
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          title={visible ? "Ocultar" : "Mostrar"}
          className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-ink"
        >
          {visible ? <EyeOff size={15} strokeWidth={1.75} /> : <Eye size={15} strokeWidth={1.75} />}
        </button>
      )}
      <button
        type="button"
        onClick={copiar}
        className={`flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors ${
          copiado ? "bg-emerald-50 text-emerald-700" : "bg-accent-light text-accent hover:bg-accent hover:text-white"
        }`}
      >
        {copiado ? <Check size={13} strokeWidth={2.25} /> : <Copy size={13} strokeWidth={2} />}
        {copiado ? "Copiado" : "Copiar"}
      </button>
    </div>
  );
}

/**
 * modo inicial:
 * - "aviso": novedad (se abre sola desde el Sidebar mientras el usuario no tenga PIN).
 * - "pedir": viene del boton PLAME de una empresa; si el usuario no tiene PIN, pasa a "crear".
 */
export default function VentanaClaveSol({ empresa = null, modo: modoInicial = "pedir", tienePin = true, onCerrar, onPinCreado }) {
  const [modo, setModo] = useState(modoInicial === "pedir" && !tienePin ? "crear" : modoInicial);
  const [pin, setPin] = useState("");
  const [pin2, setPin2] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [datos, setDatos] = useState(null);
  const [restante, setRestante] = useState(0);
  const [pinRecienCreado, setPinRecienCreado] = useState(false);
  const cerrarRef = useRef(onCerrar);
  cerrarRef.current = onCerrar;

  useEffect(() => {
    function alTeclear(e) {
      if (e.key === "Escape") cerrarRef.current();
    }
    window.addEventListener("keydown", alTeclear);
    return () => window.removeEventListener("keydown", alTeclear);
  }, []);

  // La clave se ve un rato y la ventana se cierra sola (no queda a la vista).
  useEffect(() => {
    if (!datos) return;
    if (restante <= 0) {
      setDatos(null);
      cerrarRef.current();
      return;
    }
    const t = setTimeout(() => setRestante((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [datos, restante]);

  function irA(nuevo) {
    setError("");
    setPin("");
    setPin2("");
    setPassword("");
    setModo(nuevo);
  }

  async function crearPin(e) {
    e.preventDefault();
    if (pin.length !== 4) return setError("El PIN debe tener 4 digitos.");
    if (pin !== pin2) return setError("Los dos PIN no coinciden.");
    setEnviando(true);
    setError("");
    try {
      await api.guardarPin(pin, password);
      onPinCreado?.();
      setPinRecienCreado(true);
      if (empresa) {
        irA("pedir");
      } else {
        irA("listo");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setEnviando(false);
    }
  }

  async function verClave(e) {
    e.preventDefault();
    if (pin.length !== 4) return setError("Escribe tu PIN de 4 digitos.");
    setEnviando(true);
    setError("");
    try {
      const r = await api.verClaveSol(empresa.empresa_id, pin);
      setPin("");
      setDatos(r);
      setRestante(r.visible_seg || SEGUNDOS_POR_DEFECTO);
      setModo("ver");
    } catch (err) {
      setPin("");
      setError(err.message);
    } finally {
      setEnviando(false);
    }
  }

  const titulo = {
    aviso: "Novedad: clave SOL para la PLAME",
    crear: "Crea tu PIN de 4 digitos",
    pedir: "Clave SOL para la PLAME",
    ver: "Clave SOL para la PLAME",
    listo: "Tu PIN quedo creado",
  }[modo];
  const Icono = modo === "aviso" ? Sparkles : modo === "listo" ? ShieldCheck : modo === "crear" ? Lock : KeyRound;
  const botonPrincipal =
    "flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0";

  return (
    <div data-ventana-clave-sol className="fixed inset-0 z-[60] flex items-center justify-center bg-ink/60 p-6" onClick={onCerrar}>
      <div className="w-full max-w-md rounded-2xl bg-white shadow-soft-lg" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-light text-accent">
              <Icono size={18} strokeWidth={1.75} />
            </div>
            <div className="min-w-0">
              <h3 className="text-base font-bold text-ink">{titulo}</h3>
              {empresa && (
                <p className="truncate text-xs text-slate-500" title={empresa.razon_social}>
                  {empresa.razon_social} · RUC {empresa.ruc}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={onCerrar}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Cerrar"
          >
            <X size={15} strokeWidth={1.75} />
          </button>
        </div>

        <div className="px-6 py-5">
          {modo === "aviso" && (
            <div className="space-y-4 text-sm text-slate-600">
              <p>
                La PLAME se presenta en un programa de SUNAT que pide el <strong>RUC, el usuario y la clave SOL</strong> de la
                empresa. Ya no tienes que buscarlos: ahora los copias desde aqui.
              </p>
              <div className="rounded-xl bg-slate-50 p-4">
                <p className="text-xs font-bold uppercase tracking-wide text-slate-500">Como funciona</p>
                <ol className="mt-2 list-decimal space-y-1.5 pl-4 text-[13px]">
                  <li>Crea un <strong>PIN de 4 digitos</strong> (solo tuyo). Te pediremos la contrasena de tu cuenta para confirmarlo.</li>
                  <li>
                    Ve a <strong>Cumplimiento › Declaraciones</strong> y haz clic en el boton{" "}
                    <span className="inline-flex items-center gap-0.5 rounded-full bg-accent-light px-1.5 text-[10px] font-bold text-accent">
                      <KeyRound size={10} strokeWidth={2.25} />
                      PLAME
                    </span>{" "}
                    de la empresa.
                  </li>
                  <li>Escribe tu PIN y copia el RUC, el usuario y la clave para pegarlos en el programa PLAME.</li>
                </ol>
              </div>
              <ul className="space-y-1 text-xs text-slate-500">
                <li>· Solo ves las empresas que ya puedes ver en el sistema.</li>
                <li>· La clave se muestra 60 segundos y la ventana se cierra sola.</li>
                <li>· Tras 5 PIN errados, el PIN se bloquea 15 minutos. Cada vista queda registrada.</li>
                <li>· No compartas tu PIN. Si lo olvidas, creas otro con tu contrasena.</li>
              </ul>
              <div className="flex flex-col gap-2 pt-1">
                <button onClick={() => irA("crear")} className={botonPrincipal}>
                  <Lock size={15} strokeWidth={2} />
                  Crear mi PIN
                </button>
                <button onClick={onCerrar} className="py-1.5 text-xs font-semibold text-slate-500 hover:text-ink">
                  Ahora no
                </button>
              </div>
            </div>
          )}

          {modo === "crear" && (
            <form onSubmit={crearPin} className="space-y-3">
              <p className="text-sm text-slate-600">
                Con este PIN veras la clave SOL de tus empresas para la PLAME. Evita PIN obvios como 1111 o 1234.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <CampoPin etiqueta="PIN nuevo" valor={pin} onCambio={setPin} autoFocus />
                <CampoPin etiqueta="Repite el PIN" valor={pin2} onCambio={setPin2} />
              </div>
              <label className="block text-xs font-semibold text-slate-500">
                Contrasena de tu cuenta
                <input
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none"
                />
              </label>
              {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>}
              <button type="submit" disabled={enviando || pin.length !== 4 || pin2.length !== 4 || !password} className={botonPrincipal}>
                {enviando && <Loader2 size={15} strokeWidth={2} className="animate-spin" />}
                Guardar mi PIN
              </button>
            </form>
          )}

          {modo === "pedir" && (
            <form onSubmit={verClave} className="space-y-3">
              {pinRecienCreado && (
                <p className="rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700">Tu PIN quedo guardado. Escribelo para ver la clave.</p>
              )}
              <p className="text-sm text-slate-600">Escribe tu PIN para ver el RUC, el usuario y la clave SOL de esta empresa.</p>
              <CampoPin etiqueta="Tu PIN" valor={pin} onCambio={setPin} autoFocus />
              {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>}
              <button type="submit" disabled={enviando || pin.length !== 4} className={botonPrincipal}>
                {enviando && <Loader2 size={15} strokeWidth={2} className="animate-spin" />}
                Ver clave SOL
              </button>
              <button type="button" onClick={() => irA("crear")} className="block w-full text-center text-xs font-semibold text-slate-500 hover:text-accent">
                Olvide mi PIN
              </button>
            </form>
          )}

          {modo === "ver" && datos && (
            <div className="space-y-2.5">
              <FilaDato etiqueta="RUC" valor={datos.ruc} />
              <FilaDato etiqueta="Usuario SOL" valor={datos.usuario_sol} />
              <FilaDato etiqueta="Clave SOL" valor={datos.clave_sol} secreto />
              <div className="pt-1">
                <div className="h-1 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full bg-accent transition-all duration-1000 ease-linear"
                    style={{ width: `${(restante / (datos.visible_seg || SEGUNDOS_POR_DEFECTO)) * 100}%` }}
                  />
                </div>
                <p className="mt-1.5 text-xs text-slate-500">Por seguridad esta ventana se cierra sola en {restante} s.</p>
              </div>
            </div>
          )}

          {modo === "listo" && (
            <div className="space-y-4 text-sm text-slate-600">
              <p>
                Listo. Cuando tengas que presentar una PLAME, ve a <strong>Cumplimiento › Declaraciones</strong> y usa el boton{" "}
                <strong>PLAME</strong> de la empresa.
              </p>
              <button onClick={onCerrar} className={botonPrincipal}>
                Entendido
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
