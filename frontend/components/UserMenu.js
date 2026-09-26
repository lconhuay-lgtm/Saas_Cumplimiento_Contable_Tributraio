"use client";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, LogOut, KeyRound, BellRing, Loader2, CheckCircle2 } from "lucide-react";
import { api } from "../lib/api";

// Punto 2: antes el email + "Cerrar sesion" vivian pegados abajo del todo en
// el Sidebar (facil de perder de vista con la barra larga). Ahora es un
// menu propio, fijo arriba a la derecha en toda pantalla -- mismo lugar en
// cualquier pagina porque Sidebar (que monta esto) esta en todas.
export default function UserMenu({ usuario, onUsuarioActualizado, onCerrarSesion }) {
  const [abierto, setAbierto] = useState(false);
  const contenedorRef = useRef(null);

  useEffect(() => {
    function alClicFuera(e) {
      if (contenedorRef.current && !contenedorRef.current.contains(e.target)) {
        setAbierto(false);
      }
    }
    document.addEventListener("mousedown", alClicFuera);
    return () => document.removeEventListener("mousedown", alClicFuera);
  }, []);

  const iniciales = usuario?.email ? usuario.email.slice(0, 2).toUpperCase() : "..";

  return (
    <div ref={contenedorRef} className="fixed right-6 top-4 z-40">
      <button
        onClick={() => setAbierto((v) => !v)}
        className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white py-1.5 pl-1.5 pr-2.5 shadow-soft transition-all duration-300 ease-out hover:border-slate-300"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-light text-[11px] font-bold text-accent">
          {iniciales}
        </span>
        <span className="max-w-[160px] truncate text-xs font-medium text-ink" title={usuario?.email}>
          {usuario?.email || "Cargando..."}
        </span>
        <ChevronDown size={14} strokeWidth={2} className={`text-slate-400 transition-transform duration-200 ${abierto ? "rotate-180" : ""}`} />
      </button>

      {abierto && (
        <div className="surface-card absolute right-0 mt-2 w-80 space-y-5 p-5">
          <PanelPassword />
          <div className="border-t border-slate-100 pt-4">
            <PanelNotificacion usuario={usuario} onUsuarioActualizado={onUsuarioActualizado} />
          </div>
          <div className="border-t border-slate-100 pt-4">
            <button
              onClick={onCerrarSesion}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs font-medium text-slate-500 transition-colors duration-300 ease-out hover:bg-slate-50 hover:text-ink"
            >
              <LogOut size={14} strokeWidth={1.5} />
              Cerrar sesion
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PanelPassword() {
  const [actual, setActual] = useState("");
  const [nuevo, setNuevo] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const [guardado, setGuardado] = useState(false);

  async function guardar(e) {
    e.preventDefault();
    setGuardando(true);
    setError("");
    setGuardado(false);
    try {
      await api.cambiarPassword({ password_actual: actual, password_nuevo: nuevo });
      setActual("");
      setNuevo("");
      setGuardado(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <form onSubmit={guardar} className="space-y-2">
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
        <KeyRound size={13} strokeWidth={1.75} />
        Cambiar contrasena
      </p>
      <input
        type="password"
        placeholder="Contrasena actual"
        required
        value={actual}
        onChange={(e) => {
          setActual(e.target.value);
          setGuardado(false);
        }}
        className="campo-input w-full text-sm"
      />
      <input
        type="password"
        placeholder="Contrasena nueva (minimo 8 caracteres)"
        required
        minLength={8}
        value={nuevo}
        onChange={(e) => {
          setNuevo(e.target.value);
          setGuardado(false);
        }}
        className="campo-input w-full text-sm"
      />
      {error && <p className="text-xs text-red-600">{error}</p>}
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={guardando}
          className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white transition-all duration-300 ease-out hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
        >
          {guardando && <Loader2 size={12} strokeWidth={2} className="animate-spin" />}
          Guardar
        </button>
        {guardado && (
          <span className="flex items-center gap-1 text-xs font-medium text-emerald-600">
            <CheckCircle2 size={13} strokeWidth={1.75} />
            Listo
          </span>
        )}
      </div>
    </form>
  );
}

function PanelNotificacion({ usuario, onUsuarioActualizado }) {
  const [forma, setForma] = useState(usuario?.forma_notificacion || "correo");
  const [celular, setCelular] = useState(usuario?.celular || "");
  const [pais, setPais] = useState(usuario?.pais_celular || "+51");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const [guardado, setGuardado] = useState(false);

  useEffect(() => {
    setForma(usuario?.forma_notificacion || "correo");
    setCelular(usuario?.celular || "");
    setPais(usuario?.pais_celular || "+51");
  }, [usuario]);

  async function guardar(e) {
    e.preventDefault();
    setGuardando(true);
    setError("");
    setGuardado(false);
    try {
      const actualizado = await api.actualizarPerfil({
        forma_notificacion: forma,
        celular: forma === "whatsapp" ? celular : null,
        pais_celular: forma === "whatsapp" ? pais : null,
      });
      onUsuarioActualizado?.(actualizado);
      setGuardado(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <form onSubmit={guardar} className="space-y-2">
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
        <BellRing size={13} strokeWidth={1.75} />
        Como te aviso
      </p>
      <div className="flex gap-3 text-sm text-ink">
        <label className="flex items-center gap-1.5">
          <input
            type="radio"
            name="forma_notificacion"
            checked={forma === "correo"}
            onChange={() => {
              setForma("correo");
              setGuardado(false);
            }}
          />
          Correo
        </label>
        <label className="flex items-center gap-1.5">
          <input
            type="radio"
            name="forma_notificacion"
            checked={forma === "whatsapp"}
            onChange={() => {
              setForma("whatsapp");
              setGuardado(false);
            }}
          />
          WhatsApp
        </label>
      </div>
      {forma === "whatsapp" && (
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="+51"
            value={pais}
            onChange={(e) => {
              setPais(e.target.value);
              setGuardado(false);
            }}
            className="campo-input w-16 text-sm"
          />
          <input
            type="text"
            placeholder="Numero de celular"
            required
            value={celular}
            onChange={(e) => {
              setCelular(e.target.value);
              setGuardado(false);
            }}
            className="campo-input w-full text-sm"
          />
        </div>
      )}
      {error && <p className="text-xs text-red-600">{error}</p>}
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={guardando}
          className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white transition-all duration-300 ease-out hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
        >
          {guardando && <Loader2 size={12} strokeWidth={2} className="animate-spin" />}
          Guardar
        </button>
        {guardado && (
          <span className="flex items-center gap-1 text-xs font-medium text-emerald-600">
            <CheckCircle2 size={13} strokeWidth={1.75} />
            Listo
          </span>
        )}
      </div>
    </form>
  );
}
