"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ShieldCheck, CheckCircle2, XCircle } from "lucide-react";
import { api, getToken } from "../../../lib/api";

export default function VerificarEmailPage() {
  const { token } = useParams();
  const [resultado, setResultado] = useState(null); // {ok, mensaje} | null mientras carga

  useEffect(() => {
    api
      .verificarEmail(token)
      .then((data) => setResultado({ ok: true, mensaje: data.mensaje }))
      .catch((err) => setResultado({ ok: false, mensaje: err.message }));
  }, [token]);

  const yaLogueado = !!getToken();

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-4">
      <div className="surface-card w-full max-w-sm animate-fade-in-up p-10">
        <div className="mb-8 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-light text-accent">
            <ShieldCheck size={16} strokeWidth={1.5} />
          </div>
          <span className="text-sm font-bold tracking-tight text-ink">Anzen Sol</span>
        </div>

        {resultado === null ? (
          <p className="text-sm text-slate-500">Verificando tu correo...</p>
        ) : resultado.ok ? (
          <>
            <div className="flex items-center gap-2 text-emerald-600">
              <CheckCircle2 size={20} strokeWidth={1.5} />
              <h1 className="text-lg font-bold">Correo verificado</h1>
            </div>
            <p className="mt-2 text-sm text-slate-600">{resultado.mensaje}</p>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2 text-red-600">
              <XCircle size={20} strokeWidth={1.5} />
              <h1 className="text-lg font-bold">No se pudo verificar</h1>
            </div>
            <p className="mt-2 text-sm text-slate-600">{resultado.mensaje}</p>
          </>
        )}

        <Link
          href={yaLogueado ? "/dashboard" : "/login"}
          className="mt-6 inline-block text-sm font-medium text-accent hover:underline"
        >
          {yaLogueado ? "Ir al tablero" : "Ir al inicio de sesion"}
        </Link>
      </div>
    </div>
  );
}
