"use client";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { LayoutDashboard, Building2, LogOut } from "lucide-react";
import { clearToken } from "../lib/api";

export default function NavBar() {
  const router = useRouter();
  const pathname = usePathname();

  function salir() {
    clearToken();
    router.replace("/login");
  }

  function esActiva(ruta) {
    return pathname === ruta || pathname.startsWith(`${ruta}/`);
  }

  const enlaces = [
    { href: "/dashboard", label: "Dashboard", Icon: LayoutDashboard },
    { href: "/empresas", label: "Empresas", Icon: Building2 },
  ];

  return (
    <nav className="flex items-center gap-8 border-b border-slate-100 py-4">
      <span className="text-sm font-bold tracking-tight text-ink">Buzon SUNAT</span>

      <div className="flex flex-1 gap-6">
        {enlaces.map(({ href, label, Icon }) => {
          const activo = esActiva(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-1.5 border-b-2 py-1 text-sm font-medium transition-colors duration-300 ease-out ${
                activo
                  ? "border-accent text-accent"
                  : "border-transparent text-slate-500 hover:text-ink"
              }`}
            >
              <Icon size={15} strokeWidth={1.5} />
              {label}
            </Link>
          );
        })}
      </div>

      <button
        onClick={salir}
        className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition-all duration-300 ease-out hover:border-slate-300 hover:bg-slate-50"
      >
        <LogOut size={14} strokeWidth={1.5} />
        Cerrar sesion
      </button>
    </nav>
  );
}
