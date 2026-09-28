"use client";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ShieldCheck, Loader2, CheckCircle2 } from "lucide-react";
import { api, setToken } from "../../lib/api";

// useSearchParams() exige un limite de Suspense en el build de produccion
// (next build) -- mismo fix que empresas/page.js y tareas/page.js (Fase R4).
export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginPageContenido />
    </Suspense>
  );
}

function LoginPageContenido() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const recienVerificado = searchParams.get("verificado") === "1";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [cargando, setCargando] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setCargando(true);
    try {
      const data = await api.login(email, password);
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
            <ShieldCheck size={16} strokeWidth={1.5} />
          </div>
          <span className="text-sm font-bold tracking-tight text-ink">Anzen Sol</span>
        </div>

        <h1 className="text-2xl font-extrabold tracking-tight text-ink">Inicia sesion</h1>
        <p className="mt-1 text-sm text-slate-600">Entra a tu cuenta para ver el tablero</p>

        {recienVerificado && !error && (
          <div className="mt-6 flex items-center gap-2 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-700">
            <CheckCircle2 size={15} strokeWidth={1.75} className="shrink-0" />
            Correo verificado. Ingresa tu contrasena para continuar.
          </div>
        )}

        {error && (
          <div className="mt-6 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">
            {error}
          </div>
        )}

        <div className="mt-6">
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
            Contrasena
          </label>
          <input
            id="password"
            type="password"
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
          {cargando ? "Ingresando..." : "Ingresar"}
        </button>

        <p className="mt-6 text-center text-sm text-slate-500">
          No tienes cuenta?{" "}
          <Link href="/registro" className="font-medium text-accent hover:underline">
            Crear una
          </Link>
        </p>
      </form>
    </div>
  );
}
