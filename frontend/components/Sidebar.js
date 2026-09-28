"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Building2,
  ShieldCheck,
  HeartPulse,
  CalendarDays,
  ListChecks,
  Users,
  Settings,
  MailWarning,
  Loader2,
  CheckCircle2,
  LogOut,
} from "lucide-react";
import { api, clearToken } from "../lib/api";
import { useTrabajos } from "../contexts/TrabajosContext";
import { infoEtapa, TITULO_TIPO_TRABAJO } from "../lib/etapasTrabajos";
import UserMenu from "./UserMenu";
import ModalNotificacionesNuevas from "./ModalNotificacionesNuevas";

const ENLACES = [
  { href: "/dashboard", label: "Dashboard", Icon: LayoutDashboard },
  { href: "/empresas", label: "Empresas", Icon: Building2 },
  { href: "/tareas", label: "Tareas", Icon: ListChecks },
  { href: "/cronograma", label: "Cronograma", Icon: CalendarDays },
  { href: "/salud", label: "Salud del sistema", Icon: HeartPulse, soloAdmin: true },
  { href: "/equipo", label: "Mi equipo", Icon: Users, soloAdmin: true },
  { href: "/configuracion", label: "Panel maestro", Icon: Settings, soloStaff: true },
];

export default function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const [usuario, setUsuario] = useState(null);
  const [reenviando, setReenviando] = useState(false);
  const [reenviado, setReenviado] = useState(false);
  const [comprobando, setComprobando] = useState(false);
  const [notificaciones, setNotificaciones] = useState([]);
  const { trabajosActivos } = useTrabajos();

  useEffect(() => {
    api.me().then(setUsuario).catch(() => {});
  }, []);

  useEffect(() => {
    // Solo se pide si el correo ya esta verificado -- si no, la pantalla de
    // bloqueo de arriba ya cubre toda la app y esta ventana no tendria
    // donde mostrarse. Se dispara una vez por montaje de Sidebar (cada
    // pagina protegida lo monta de nuevo al navegar), pero como el "visto"
    // vive en la base de datos (MensajeBuzon.notificado_popup), en cuanto
    // se marcan vistos ya no vuelven a aparecer en la siguiente consulta.
    if (!usuario?.email_verificado) return;
    api
      .listarNotificacionesNuevas()
      .then((grupos) => setNotificaciones(grupos))
      .catch(() => {});
  }, [usuario?.email_verificado]);

  function irAEmpresa(grupo) {
    api.marcarNotificacionesVistas(grupo.mensajes.map((m) => m.id)).catch(() => {});
    setNotificaciones((actual) => actual.filter((g) => g.empresa_id !== grupo.empresa_id));
    router.push(`/empresas/${grupo.empresa_id}`);
  }

  function cerrarNotificaciones() {
    const todosLosIds = notificaciones.flatMap((g) => g.mensajes.map((m) => m.id));
    if (todosLosIds.length > 0) {
      api.marcarNotificacionesVistas(todosLosIds).catch(() => {});
    }
    setNotificaciones([]);
  }

  function salir() {
    clearToken();
    router.replace("/login");
  }

  function esActiva(ruta) {
    return pathname === ruta || pathname.startsWith(`${ruta}/`);
  }

  async function reenviarVerificacion() {
    setReenviando(true);
    try {
      await api.reenviarVerificacion();
      setReenviado(true);
    } catch (err) {
      alert(err.message);
    } finally {
      setReenviando(false);
    }
  }

  async function comprobarVerificacion() {
    setComprobando(true);
    try {
      const actualizado = await api.me();
      if (actualizado.email_verificado) {
        // No lo dejamos seguir con la sesion que ya tenia abierta desde el
        // registro -- se cierra y se manda a /login para que tenga que
        // volver a escribir su contrasena (pedido explicito, evita entrar
        // "de arrastre" solo por haber confirmado el correo).
        clearToken();
        router.replace("/login?verificado=1");
        return;
      }
      setUsuario(actualizado);
      alert("Todavia no detectamos la verificacion -- revisa que hayas hecho clic en el link del correo.");
    } catch (err) {
      alert(err.message);
    } finally {
      setComprobando(false);
    }
  }

  return (
    <>
      <UserMenu usuario={usuario} onUsuarioActualizado={setUsuario} onCerrarSesion={salir} />
      <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col bg-ink">
      <div className="flex items-center gap-2.5 px-5 py-6">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-white">
          <ShieldCheck size={16} strokeWidth={1.5} />
        </div>
        <span className="font-heading text-base font-bold tracking-tight text-white">Anzen Sol</span>
      </div>

      <nav className="flex-1 space-y-1 px-3">
        {ENLACES.filter(
          (enlace) =>
            (!enlace.soloAdmin || usuario?.rol === "admin") &&
            (!enlace.soloStaff || usuario?.es_staff_plataforma)
        ).map(({ href, label, Icon }) => {
          const activo = esActiva(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors duration-300 ease-out ${
                activo ? "bg-accent text-white" : "text-slate-400 hover:bg-white/5 hover:text-white"
              }`}
            >
              <Icon size={17} strokeWidth={1.5} />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Trabajos en curso (consulta al buzon, Ficha RUC, Reporte
          Tributario) -- vive de TrabajosContext (montado en app/layout.js,
          nunca se desmonta al navegar), asi que sigue visible aunque el
          usuario haya salido de la pantalla donde disparo la accion. Antes
          esto se perdia al cambiar de modulo aunque el trabajo siguiera
          corriendo en el servidor (reportado en produccion, 25/09). */}
      {trabajosActivos.length > 0 && (
        <div className="mx-3 mb-3 space-y-2.5 rounded-lg border border-white/10 bg-white/5 px-3 py-2.5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {trabajosActivos.length} trabajo{trabajosActivos.length === 1 ? "" : "s"} en curso
          </p>
          {trabajosActivos.map((t) => {
            const { etiqueta, porcentaje } = infoEtapa(t.tipo, t.etapa);
            return (
              <div key={`${t.tipo}:${t.empresaId}`} className="space-y-1">
                <div className="flex items-center gap-1.5 text-[11px] text-slate-300">
                  <Loader2 size={11} strokeWidth={2} className="shrink-0 animate-spin" />
                  <span className="truncate" title={t.empresaNombre}>
                    {t.empresaNombre || "Empresa"}
                  </span>
                </div>
                <p className="truncate text-[10px] text-slate-500" title={etiqueta}>
                  {TITULO_TIPO_TRABAJO[t.tipo]} &middot; {etiqueta}
                </p>
                <div className="h-1 w-full overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-accent transition-all duration-500"
                    style={{ width: `${porcentaje}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}

    </aside>

    {usuario && !usuario.email_verificado && (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-white p-6">
        <div className="w-full max-w-md rounded-2xl bg-white p-8 text-center shadow-soft-lg ring-1 ring-slate-100">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-amber-100 text-amber-600">
            <MailWarning size={22} strokeWidth={1.75} />
          </div>
          <h2 className="mt-4 text-lg font-bold text-ink">Verifica tu correo para continuar</h2>
          <p className="mt-2 text-sm text-slate-600">
            Te enviamos un link de verificacion a <span className="font-semibold text-ink">{usuario.email}</span>.
            Abrelo desde tu bandeja de entrada para poder usar Anzen Sol.
          </p>

          <button
            onClick={comprobarVerificacion}
            disabled={comprobando}
            className="mt-6 flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
          >
            {comprobando ? (
              <Loader2 size={15} strokeWidth={2} className="animate-spin" />
            ) : (
              <CheckCircle2 size={15} strokeWidth={1.75} />
            )}
            Ya verifique mi correo
          </button>

          {reenviado ? (
            <p className="mt-3 text-xs text-slate-500">Te mandamos un correo nuevo con el link.</p>
          ) : (
            <button
              onClick={reenviarVerificacion}
              disabled={reenviando}
              className="mt-3 flex w-full items-center justify-center gap-1 text-xs font-medium text-accent hover:underline disabled:opacity-60"
            >
              {reenviando && <Loader2 size={11} strokeWidth={2} className="animate-spin" />}
              Reenviar correo de verificacion
            </button>
          )}

          <button
            onClick={salir}
            className="mt-5 flex w-full items-center justify-center gap-1 text-xs font-medium text-slate-400 hover:text-slate-600"
          >
            <LogOut size={12} strokeWidth={1.75} />
            Me registre con el correo equivocado -- cerrar sesion
          </button>
        </div>
      </div>
    )}

    {usuario?.email_verificado && notificaciones.length > 0 && (
      <ModalNotificacionesNuevas
        grupos={notificaciones}
        onIrAEmpresa={irAEmpresa}
        onCerrar={cerrarNotificaciones}
      />
    )}
    </>
  );
}
