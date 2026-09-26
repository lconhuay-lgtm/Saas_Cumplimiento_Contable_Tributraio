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
} from "lucide-react";
import { api, clearToken } from "../lib/api";
import { useTrabajos } from "../contexts/TrabajosContext";
import { infoEtapa, TITULO_TIPO_TRABAJO } from "../lib/etapasTrabajos";
import UserMenu from "./UserMenu";

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
  const { trabajosActivos } = useTrabajos();

  useEffect(() => {
    api.me().then(setUsuario).catch(() => {});
  }, []);

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

      {usuario && !usuario.email_verificado && (
        <div className="mx-3 mb-3 rounded-lg border border-amber-400/20 bg-amber-400/10 px-3 py-2.5">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-300">
            <MailWarning size={13} strokeWidth={1.75} />
            Verifica tu correo
          </div>
          {reenviado ? (
            <p className="mt-1 text-[11px] text-amber-200/80">Te mandamos un correo con el link.</p>
          ) : (
            <>
              <p className="mt-1 text-[11px] text-amber-200/70">Revisa tu bandeja o reenvia el link.</p>
              <button
                onClick={reenviarVerificacion}
                disabled={reenviando}
                className="mt-1.5 flex items-center gap-1 text-[11px] font-semibold text-amber-300 hover:underline disabled:opacity-60"
              >
                {reenviando && <Loader2 size={11} strokeWidth={2} className="animate-spin" />}
                Reenviar correo
              </button>
            </>
          )}
        </div>
      )}

    </aside>
    </>
  );
}
