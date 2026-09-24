"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { LayoutDashboard, Building2, LogOut, Inbox, HeartPulse, CalendarDays, ListChecks, Users } from "lucide-react";
import { api, clearToken } from "../lib/api";

const ENLACES = [
  { href: "/dashboard", label: "Dashboard", Icon: LayoutDashboard },
  { href: "/empresas", label: "Empresas", Icon: Building2 },
  { href: "/tareas", label: "Tareas", Icon: ListChecks },
  { href: "/cronograma", label: "Cronograma", Icon: CalendarDays },
  { href: "/salud", label: "Salud del sistema", Icon: HeartPulse, soloAdmin: true },
  { href: "/equipo", label: "Mi equipo", Icon: Users, soloAdmin: true },
];

export default function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const [usuario, setUsuario] = useState(null);

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

  const iniciales = usuario?.email ? usuario.email.slice(0, 2).toUpperCase() : "..";

  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col bg-ink">
      <div className="flex items-center gap-2.5 px-5 py-6">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-white">
          <Inbox size={16} strokeWidth={1.5} />
        </div>
        <span className="font-heading text-base font-bold tracking-tight text-white">Buzon SUNAT</span>
      </div>

      <nav className="flex-1 space-y-1 px-3">
        {ENLACES.filter((enlace) => !enlace.soloAdmin || usuario?.rol === "admin").map(({ href, label, Icon }) => {
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

      <div className="border-t border-white/10 px-3 py-4">
        <div className="flex items-center gap-2.5 rounded-lg px-2 py-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-light text-xs font-bold text-accent">
            {iniciales}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-white" title={usuario?.email}>
              {usuario?.email || "Cargando..."}
            </p>
            <p className="text-[11px] text-slate-500">Conectado</p>
          </div>
        </div>
        <button
          onClick={salir}
          className="mt-1 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium text-slate-400 transition-colors duration-300 ease-out hover:bg-white/5 hover:text-white"
        >
          <LogOut size={14} strokeWidth={1.5} />
          Cerrar sesion
        </button>
      </div>
    </aside>
  );
}
