"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Users, UserPlus, Copy, X, Loader2, Mail, CheckCircle2, Ban } from "lucide-react";
import Sidebar from "../../components/Sidebar";
import ConfirmDialog from "../../components/ConfirmDialog";
import { api, getToken } from "../../lib/api";

function formatoFecha(fechaIso) {
  return new Date(fechaIso).toLocaleDateString("es-PE", { day: "2-digit", month: "short", year: "numeric" });
}

function estadoInvitacion(inv) {
  if (inv.cancelado_en) return { etiqueta: "Cancelada", color: "bg-slate-100 text-slate-500", Icon: Ban };
  if (inv.usado_en) return { etiqueta: "Aceptada", color: "bg-emerald-100 text-emerald-700", Icon: CheckCircle2 };
  if (new Date(inv.expira_en) < new Date()) return { etiqueta: "Vencida", color: "bg-amber-100 text-amber-700", Icon: Mail };
  return { etiqueta: "Pendiente", color: "bg-blue-100 text-blue-700", Icon: Mail };
}

export default function EquipoPage() {
  const router = useRouter();
  const [usuarios, setUsuarios] = useState([]);
  const [invitaciones, setInvitaciones] = useState([]);
  const [empresas, setEmpresas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");
  const [emailNuevo, setEmailNuevo] = useState("");
  const [rolNuevo, setRolNuevo] = useState("miembro");
  const [empresaIdsNuevo, setEmpresaIdsNuevo] = useState([]);
  const [invitando, setInvitando] = useState(false);
  const [copiadoId, setCopiadoId] = useState(null);
  const [invitacionACancelar, setInvitacionACancelar] = useState(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function cargar() {
    setCargando(true);
    setError("");
    try {
      const [datosUsuarios, datosInvitaciones, datosEmpresas] = await Promise.all([
        api.listarUsuarios(),
        api.listarInvitaciones(),
        api.listarEmpresas(),
      ]);
      setUsuarios(datosUsuarios);
      setInvitaciones(datosInvitaciones);
      setEmpresas(datosEmpresas);
    } catch (err) {
      setError(err.message);
    } finally {
      setCargando(false);
    }
  }

  function alternarEmpresa(id) {
    setEmpresaIdsNuevo((actual) =>
      actual.includes(id) ? actual.filter((x) => x !== id) : [...actual, id]
    );
  }

  async function invitar(e) {
    e.preventDefault();
    setInvitando(true);
    setError("");
    try {
      const nueva = await api.crearInvitacion(
        emailNuevo.trim(),
        rolNuevo,
        rolNuevo === "miembro" ? empresaIdsNuevo : []
      );
      setEmailNuevo("");
      setRolNuevo("miembro");
      setEmpresaIdsNuevo([]);
      await cargar();
      copiarLink(nueva);
    } catch (err) {
      setError(err.message);
    } finally {
      setInvitando(false);
    }
  }

  async function cancelar(inv) {
    setInvitacionACancelar(null);
    try {
      await api.cancelarInvitacion(inv.id);
      cargar();
    } catch (err) {
      alert(err.message);
    }
  }

  function copiarLink(inv) {
    navigator.clipboard?.writeText(inv.link).then(() => {
      setCopiadoId(inv.id);
      setTimeout(() => setCopiadoId(null), 2000);
    });
  }

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 py-8 xl:px-12">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-ink">Mi equipo</h1>
          <p className="mt-1 text-sm text-slate-600">
            Usuarios que comparten esta cuenta -- invita a un companero para que vea las mismas empresas y le puedas
            asignar su propia cartera.
          </p>
        </div>

        {error && (
          <div className="mt-6 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
        )}

        <form onSubmit={invitar} className="surface-card mt-6 flex flex-wrap items-end gap-3 p-5">
          <div className="min-w-[240px] flex-1">
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-500">
              Invitar por email
            </label>
            <input
              type="email"
              required
              value={emailNuevo}
              onChange={(e) => setEmailNuevo(e.target.value)}
              placeholder="companero@tuestudio.com"
              className="campo-input"
            />
          </div>
          <div className="min-w-[160px]">
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-500">
              Categoria
            </label>
            <select
              value={rolNuevo}
              onChange={(e) => setRolNuevo(e.target.value)}
              className="campo-input"
            >
              <option value="miembro">Usuario</option>
              <option value="admin">Administrador</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={invitando}
            className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white shadow-soft transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-60"
          >
            {invitando ? <Loader2 size={15} strokeWidth={2} className="animate-spin" /> : <UserPlus size={15} strokeWidth={1.5} />}
            Invitar
          </button>

          {rolNuevo === "miembro" && (
            <div className="w-full">
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-slate-500">
                Empresas asignadas (solo para "Usuario" -- un Administrador ve todas)
              </label>
              {empresas.length === 0 ? (
                <p className="text-xs text-slate-400">No hay empresas registradas todavia.</p>
              ) : (
                <div className="flex max-h-32 flex-wrap gap-2 overflow-y-auto rounded-lg border border-slate-200 p-2.5">
                  {empresas.map((emp) => (
                    <label
                      key={emp.id}
                      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                        empresaIdsNuevo.includes(emp.id)
                          ? "border-accent bg-accent/10 text-accent-dark"
                          : "border-slate-200 text-slate-600 hover:border-slate-300"
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={empresaIdsNuevo.includes(emp.id)}
                        onChange={() => alternarEmpresa(emp.id)}
                      />
                      {emp.razon_social || emp.ruc}
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}
        </form>

        {cargando ? (
          <p className="mt-8 text-sm text-slate-500">Cargando...</p>
        ) : (
          <>
            <h2 className="mt-8 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-slate-500">
              <Users size={14} strokeWidth={1.75} />
              Usuarios activos ({usuarios.length})
            </h2>
            <div className="surface-card mt-3 divide-y divide-slate-100 overflow-hidden">
              {usuarios.map((u) => (
                <div key={u.id} className="flex items-center justify-between gap-3 px-5 py-3.5">
                  <span className="text-sm font-medium text-ink">{u.email}</span>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold uppercase text-slate-500">
                    {u.rol}
                  </span>
                </div>
              ))}
            </div>

            {invitaciones.length > 0 && (
              <>
                <h2 className="mt-8 text-xs font-bold uppercase tracking-wide text-slate-500">Invitaciones</h2>
                <div className="surface-card mt-3 divide-y divide-slate-100 overflow-hidden">
                  {invitaciones.map((inv) => {
                    const est = estadoInvitacion(inv);
                    const pendiente = est.etiqueta === "Pendiente";
                    return (
                      <div key={inv.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-ink">{inv.email}</span>
                            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold uppercase text-slate-500">
                              {inv.rol === "admin" ? "Administrador" : "Usuario"}
                            </span>
                            <span className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${est.color}`}>
                              <est.Icon size={11} strokeWidth={2} />
                              {est.etiqueta}
                            </span>
                          </div>
                          <p className="mt-0.5 text-xs text-slate-500">
                            Invitado por {inv.invitado_por_email} el {formatoFecha(inv.creado_en)}
                            {pendiente && ` -- vence el ${formatoFecha(inv.expira_en)}`}
                          </p>
                          {inv.rol === "miembro" && (
                            <p className="mt-0.5 text-xs text-slate-500">
                              {inv.empresa_ids.length === 0
                                ? "Sin empresas asignadas todavia"
                                : `${inv.empresa_ids.length} empresa(s) asignada(s): ${inv.empresa_ids
                                    .map((id) => empresas.find((e) => e.id === id)?.razon_social || id)
                                    .join(", ")}`}
                            </p>
                          )}
                        </div>
                        {pendiente && (
                          <div className="flex shrink-0 items-center gap-1">
                            <button
                              onClick={() => copiarLink(inv)}
                              title="Copiar link de invitacion"
                              className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:border-accent hover:text-accent"
                            >
                              <Copy size={12} strokeWidth={1.5} />
                              {copiadoId === inv.id ? "Copiado" : "Copiar link"}
                            </button>
                            <button
                              onClick={() => setInvitacionACancelar(inv)}
                              className="flex items-center justify-center rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
                              aria-label="Cancelar invitacion"
                            >
                              <X size={14} strokeWidth={1.5} />
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </>
        )}
      </main>

      {invitacionACancelar && (
        <ConfirmDialog
          titulo={`Cancelar la invitacion a ${invitacionACancelar.email}?`}
          textoConfirmar="Si, cancelar"
          peligroso
          onConfirmar={() => cancelar(invitacionACancelar)}
          onCancelar={() => setInvitacionACancelar(null)}
        />
      )}
    </div>
  );
}
