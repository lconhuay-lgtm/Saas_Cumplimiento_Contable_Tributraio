"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Inbox, Loader2 } from "lucide-react";
import { api, setToken } from "../../lib/api";

export default function RegistroPage() {
  const router = useRouter();
  const [nombreTenant, setNombreTenant] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [cargando, setCargando] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setCargando(true);
    try {
      const data = await api.registro(nombreTenant, email, password);
      setToken(data.access_token);
      router.push("/dashboard");
    } catch (err) {
      setError(err.message);
    } finally {
      setCargando(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-4">
      <form
        onSubmit={onSubmit}
        className="surface-card w-full max-w-sm animate-fade-in-up p-10"
      >
        <div className="mb-8 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-light text-accent">
            <Inbox size={16} strokeWidth={1.5} />
          </div>
          <span className="text-sm font-bold tracking-tight text-ink">Buzon SUNAT</span>
        </div>

        <h1 className="text-2xl font-extrabold tracking-tight text-ink">Crear cuenta</h1>
        <p className="mt-1 text-sm text-slate-600">Registra tu estudio contable</p>

        {error && (
          <div className="mt-6 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">
            {error}
          </div>
        )}

        <div className="mt-6">
          <label
            htmlFor="nombreTenant"
            className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-500"
          >
            Nombre del estudio / empresa
          </label>
          <input
            id="nombreTenant"
            value={nombreTenant}
            onChange={(e) => setNombreTenant(e.target.value)}
            required
            className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-ink outline-none transition-all duration-300 ease-out focus:border-accent focus:ring-4 focus:ring-accent-light"
          />
        </div>

        <div className="mt-4">
          <label htmlFor="email" className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-500">
            Email
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-ink outline-none transition-all duration-300 ease-out focus:border-accent focus:ring-4 focus:ring-accent-light"
          />
        </div>

        <div className="mt-4">
          <label
            htmlFor="password"
            className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-500"
          >
            Contrasena (minimo 8 caracteres)
          </label>
          <input
            id="password"
            type="password"
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-ink outline-none transition-all duration-300 ease-out focus:border-accent focus:ring-4 focus:ring-accent-light"
          />
        </div>

        <button
          type="submit"
          disabled={cargando}
          className="mt-7 flex w-full items-center justify-center gap-2 rounded-lg bg-accent py-2.5 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
        >
          {cargando && <Loader2 size={15} strokeWidth={2} className="animate-spin" />}
          {cargando ? "Creando..." : "Crear cuenta"}
        </button>

        <p className="mt-6 text-center text-sm text-slate-500">
          Ya tienes cuenta?{" "}
          <Link href="/login" className="font-medium text-accent hover:underline">
            Ingresar
          </Link>
        </p>
      </form>
    </div>
  );
}
