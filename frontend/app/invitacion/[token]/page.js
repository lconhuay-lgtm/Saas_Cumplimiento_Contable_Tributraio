"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ShieldCheck, Loader2, XCircle } from "lucide-react";
import { api, setToken } from "../../../lib/api";

export default function AceptarInvitacionPage() {
  const { token } = useParams();
  const router = useRouter();
  const [info, setInfo] = useState(null); // {valido, motivo_invalido, tenant_nombre, email} | null mientras carga
  const [password, setPassword] = useState("");
  const [confirmacion, setConfirmacion] = useState("");
  const [error, setError] = useState("");
  const [cargando, setCargando] = useState(false);

  useEffect(() => {
    api
      .infoInvitacion(token)
      .then(setInfo)
      .catch(() => setInfo({ valido: false, motivo_invalido: "No se pudo verificar esta invitacion." }));
  }, [token]);

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    if (password !== confirmacion) {
      setError("Las contrasenas no coinciden.");
      return;
    }
    setCargando(true);
    try {
      const data = await api.aceptarInvitacion(token, password);
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
      <div className="surface-card w-full max-w-sm animate-fade-in-up p-10">
        <div className="mb-8 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-light text-accent">
            <ShieldCheck size={16} strokeWidth={1.5} />
          </div>
          <span className="text-sm font-bold tracking-tight text-ink">Anzen Sol</span>
        </div>

        {info === null ? (
          <p className="text-sm text-slate-500">Verificando invitacion...</p>
        ) : !info.valido ? (
          <>
            <div className="flex items-center gap-2 text-red-600">
              <XCircle size={20} strokeWidth={1.5} />
              <h1 className="text-lg font-bold">Invitacion no valida</h1>
            </div>
            <p className="mt-2 text-sm text-slate-600">{info.motivo_invalido}</p>
            <Link href="/login" className="mt-6 inline-block text-sm font-medium text-accent hover:underline">
              Ir al inicio de sesion
            </Link>
          </>
        ) : (
          <>
            <h1 className="text-2xl font-extrabold tracking-tight text-ink">Unite a {info.tenant_nombre}</h1>
            <p className="mt-1 text-sm text-slate-600">
              Crea tu contrasena para <span className="font-medium text-ink">{info.email}</span>
            </p>

            {error && (
              <div className="mt-6 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">
                {error}
              </div>
            )}

            <form onSubmit={onSubmit}>
              <div className="mt-6">
                <label htmlFor="password" className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-500">
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

              <div className="mt-4">
                <label htmlFor="confirmacion" className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-500">
                  Repetir contrasena
                </label>
                <input
                  id="confirmacion"
                  type="password"
                  minLength={8}
                  value={confirmacion}
                  onChange={(e) => setConfirmacion(e.target.value)}
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
                {cargando ? "Creando cuenta..." : "Aceptar y crear mi cuenta"}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
