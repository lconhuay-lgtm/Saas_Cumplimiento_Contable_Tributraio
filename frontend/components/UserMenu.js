"use client";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, LogOut, User, ShieldCheck, BellRing, X, Loader2, CheckCircle2 } from "lucide-react";
import { api } from "../lib/api";

// Punto 2: antes el email + "Cerrar sesion" vivian pegados abajo del todo en
// el Sidebar. Ahora es una barra superior fija (a la derecha del Sidebar,
// mismo lugar en cualquier pagina porque esto se monta desde Sidebar) --
// asi el contenido propio de cada pagina (ej. el boton "Consulta masiva" de
// Dashboard/Empresas) ya no queda tapado, porque cada pagina reserva un
// pt-24 en su <main> para esta barra (ver app/*/page.js).
const TABS = [
  { id: "perfil", etiqueta: "Perfil", Icon: User },
  { id: "seguridad", etiqueta: "Seguridad", Icon: ShieldCheck },
  { id: "notificaciones", etiqueta: "Notificaciones", Icon: BellRing },
];

const ITEM_MENU = "flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-sm text-slate-600 transition-colors duration-150 hover:bg-slate-50 hover:text-ink";

export default function UserMenu({ usuario, onUsuarioActualizado, onCerrarSesion }) {
  const [menuAbierto, setMenuAbierto] = useState(false);
  const [tabModal, setTabModal] = useState(null);
  const menuRef = useRef(null);

  useEffect(() => {
    function alClicFuera(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuAbierto(false);
    }
    document.addEventListener("mousedown", alClicFuera);
    return () => document.removeEventListener("mousedown", alClicFuera);
  }, []);

  const iniciales = usuario?.email ? usuario.email.slice(0, 2).toUpperCase() : "..";
  const nombreCompleto = [usuario?.nombre, usuario?.apellidos].filter(Boolean).join(" ") || usuario?.email;

  function abrirTab(tab) {
    setTabModal(tab);
    setMenuAbierto(false);
  }

  return (
    <>
      <div className="fixed left-60 right-0 top-0 z-30 flex h-16 items-center justify-end border-b border-slate-100 bg-white/90 px-6 backdrop-blur-sm">
        <div ref={menuRef} className="relative">
          <button
            onClick={() => setMenuAbierto((v) => !v)}
            className="flex items-center gap-2 rounded-lg py-1.5 pl-1.5 pr-2 transition-colors duration-200 ease-out hover:bg-slate-50"
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-light text-xs font-bold text-accent">
              {iniciales}
            </span>
            <span className="max-w-[160px] truncate text-sm font-medium text-ink" title={usuario?.email}>
              {nombreCompleto}
            </span>
            <ChevronDown
              size={14}
              strokeWidth={2}
              className={`text-slate-400 transition-transform duration-200 ${menuAbierto ? "rotate-180" : ""}`}
            />
          </button>

          {menuAbierto && (
            <div className="absolute right-0 top-full mt-2 w-64 overflow-hidden rounded-xl border border-slate-100 bg-white py-1.5 shadow-soft-lg">
              <div className="border-b border-slate-100 px-3.5 py-3">
                <p className="truncate text-sm font-semibold text-ink" title={nombreCompleto}>
                  {nombreCompleto}
                </p>
                <p className="truncate text-xs text-slate-500" title={usuario?.email}>
                  {usuario?.email}
                </p>
              </div>
              <div className="py-1">
                {TABS.map(({ id, etiqueta, Icon }) => (
                  <button key={id} onClick={() => abrirTab(id)} className={ITEM_MENU}>
                    <Icon size={15} strokeWidth={1.75} />
                    {etiqueta}
                  </button>
                ))}
              </div>
              <div className="border-t border-slate-100 py-1">
                <button
                  onClick={() => {
                    setMenuAbierto(false);
                    onCerrarSesion();
                  }}
                  className={ITEM_MENU}
                >
                  <LogOut size={15} strokeWidth={1.75} />
                  Cerrar sesion
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {tabModal && (
        <ModalCuenta
          tabInicial={tabModal}
          usuario={usuario}
          onUsuarioActualizado={onUsuarioActualizado}
          onCerrar={() => setTabModal(null)}
        />
      )}
    </>
  );
}

function ModalCuenta({ tabInicial, usuario, onUsuarioActualizado, onCerrar }) {
  const [tab, setTab] = useState(tabInicial);
  const tabActiva = TABS.find((t) => t.id === tab);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-6" onClick={onCerrar}>
      <div
        className="flex w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-soft-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <nav className="w-48 shrink-0 space-y-1 border-r border-slate-100 bg-slate-50/70 p-3">
          <p className="px-2.5 pb-2 pt-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Mi cuenta</p>
          {TABS.map(({ id, etiqueta, Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-200 ease-out ${
                tab === id ? "bg-accent text-white" : "text-slate-600 hover:bg-white hover:text-ink"
              }`}
            >
              <Icon size={15} strokeWidth={1.75} />
              {etiqueta}
            </button>
          ))}
        </nav>

        <div className="min-w-0 flex-1 p-6">
          <div className="mb-5 flex items-center justify-between">
            <h3 className="text-base font-bold text-ink">{tabActiva?.etiqueta}</h3>
            <button
              onClick={onCerrar}
              className="rounded-lg p-1.5 text-slate-400 transition-colors duration-150 ease-out hover:bg-slate-100 hover:text-ink"
            >
              <X size={16} strokeWidth={2} />
            </button>
          </div>

          {tab === "perfil" && <TabPerfil usuario={usuario} onUsuarioActualizado={onUsuarioActualizado} />}
          {tab === "seguridad" && <TabSeguridad />}
          {tab === "notificaciones" && <TabNotificaciones usuario={usuario} onUsuarioActualizado={onUsuarioActualizado} />}
        </div>
      </div>
    </div>
  );
}

function BotonGuardar({ guardando, guardado }) {
  return (
    <div className="flex items-center gap-3 pt-1">
      <button
        type="submit"
        disabled={guardando}
        className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
      >
        {guardando && <Loader2 size={14} strokeWidth={2} className="animate-spin" />}
        Guardar cambios
      </button>
      {guardado && (
        <span className="flex items-center gap-1 text-sm font-medium text-emerald-600">
          <CheckCircle2 size={15} strokeWidth={1.75} />
          Guardado
        </span>
      )}
    </div>
  );
}

const ETIQUETA_CAMPO = "mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500";

function TabPerfil({ usuario, onUsuarioActualizado }) {
  const [nombre, setNombre] = useState(usuario?.nombre || "");
  const [apellidos, setApellidos] = useState(usuario?.apellidos || "");
  const [pais, setPais] = useState(usuario?.pais_celular || "+51");
  const [celular, setCelular] = useState(usuario?.celular || "");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const [guardado, setGuardado] = useState(false);

  useEffect(() => {
    setNombre(usuario?.nombre || "");
    setApellidos(usuario?.apellidos || "");
    setPais(usuario?.pais_celular || "+51");
    setCelular(usuario?.celular || "");
  }, [usuario]);

  function marcarSucio() {
    setGuardado(false);
  }

  async function guardar(e) {
    e.preventDefault();
    setGuardando(true);
    setError("");
    setGuardado(false);
    try {
      const actualizado = await api.actualizarPerfil({ nombre, apellidos, celular, pais_celular: pais });
      onUsuarioActualizado?.(actualizado);
      setGuardado(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <form onSubmit={guardar} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={ETIQUETA_CAMPO}>Nombre</label>
          <input
            value={nombre}
            onChange={(e) => {
              setNombre(e.target.value);
              marcarSucio();
            }}
            placeholder="Tu nombre"
            className="campo-input w-full"
          />
        </div>
        <div>
          <label className={ETIQUETA_CAMPO}>Apellidos</label>
          <input
            value={apellidos}
            onChange={(e) => {
              setApellidos(e.target.value);
              marcarSucio();
            }}
            placeholder="Tus apellidos"
            className="campo-input w-full"
          />
        </div>
      </div>

      <div>
        <label className={ETIQUETA_CAMPO}>Correo</label>
        <input value={usuario?.email || ""} disabled className="campo-input w-full bg-slate-50 text-slate-400" />
      </div>

      <div className="grid grid-cols-[88px_1fr] gap-3">
        <div>
          <label className={ETIQUETA_CAMPO}>Pais</label>
          <input
            value={pais}
            onChange={(e) => {
              setPais(e.target.value);
              marcarSucio();
            }}
            placeholder="+51"
            className="campo-input w-full"
          />
        </div>
        <div>
          <label className={ETIQUETA_CAMPO}>Celular</label>
          <input
            value={celular}
            onChange={(e) => {
              setCelular(e.target.value);
              marcarSucio();
            }}
            placeholder="999 999 999"
            className="campo-input w-full"
          />
        </div>
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}
      <BotonGuardar guardando={guardando} guardado={guardado} />
    </form>
  );
}

function TabSeguridad() {
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
    <form onSubmit={guardar} className="space-y-4">
      <div>
        <label className={ETIQUETA_CAMPO}>Contrasena actual</label>
        <input
          type="password"
          required
          value={actual}
          onChange={(e) => {
            setActual(e.target.value);
            setGuardado(false);
          }}
          className="campo-input w-full"
        />
      </div>
      <div>
        <label className={ETIQUETA_CAMPO}>Contrasena nueva</label>
        <input
          type="password"
          required
          minLength={8}
          value={nuevo}
          onChange={(e) => {
            setNuevo(e.target.value);
            setGuardado(false);
          }}
          className="campo-input w-full"
        />
        <p className="mt-1 text-xs text-slate-500">Minimo 8 caracteres.</p>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
      <BotonGuardar guardando={guardando} guardado={guardado} />
    </form>
  );
}

function TabNotificaciones({ usuario, onUsuarioActualizado }) {
  const [forma, setForma] = useState(usuario?.forma_notificacion || "correo");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const [guardado, setGuardado] = useState(false);

  useEffect(() => {
    setForma(usuario?.forma_notificacion || "correo");
  }, [usuario]);

  function elegir(valor) {
    setForma(valor);
    setGuardado(false);
  }

  async function guardar(e) {
    e.preventDefault();
    setGuardando(true);
    setError("");
    setGuardado(false);
    try {
      const actualizado = await api.actualizarPerfil({ forma_notificacion: forma });
      onUsuarioActualizado?.(actualizado);
      setGuardado(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <form onSubmit={guardar} className="space-y-4">
      <p className="text-sm text-slate-600">
        Elige como te avisamos cuando encontramos mensajes nuevos en el Buzon de Notificaciones.
      </p>

      <div className="space-y-2">
        <label
          className={`flex cursor-pointer items-center gap-3 rounded-lg border px-3.5 py-3 transition-colors duration-150 ease-out ${
            forma === "correo" ? "border-accent bg-accent-light/50" : "border-slate-200 hover:border-slate-300"
          }`}
        >
          <input type="radio" className="accent-accent" checked={forma === "correo"} onChange={() => elegir("correo")} />
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink">Correo</p>
            <p className="truncate text-xs text-slate-500">{usuario?.email}</p>
          </div>
        </label>

        <label
          className={`flex cursor-pointer items-center gap-3 rounded-lg border px-3.5 py-3 transition-colors duration-150 ease-out ${
            forma === "whatsapp" ? "border-accent bg-accent-light/50" : "border-slate-200 hover:border-slate-300"
          }`}
        >
          <input type="radio" className="accent-accent" checked={forma === "whatsapp"} onChange={() => elegir("whatsapp")} />
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink">WhatsApp</p>
            <p className="truncate text-xs text-slate-500">
              {usuario?.celular ? `${usuario.pais_celular || ""} ${usuario.celular}` : "Configura tu celular en la pestana Perfil"}
            </p>
          </div>
        </label>
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}
      <BotonGuardar guardando={guardando} guardado={guardado} />
    </form>
  );
}
