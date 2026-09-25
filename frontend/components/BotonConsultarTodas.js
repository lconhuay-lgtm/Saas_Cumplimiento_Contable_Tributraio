"use client";
import { Loader2, Zap } from "lucide-react";

// "Consultar todas" espacia cada empresa ~45s de la siguiente para no
// parecer trafico sospechoso ante SUNAT -- con varias decenas de empresas
// eso ya son horas, no "unos minutos". Mostrar la estimacion real evita
// que el boton parezca colgado cuando en realidad esta avanzando bien,
// solo que despacio por diseño.
export function formatoDuracionEstimada(cantidadEmpresas, espaciadoSeg = 45) {
  const totalMin = Math.ceil((cantidadEmpresas * espaciadoSeg) / 60);
  if (totalMin < 60) return `~${totalMin} minuto${totalMin === 1 ? "" : "s"}`;
  const horas = Math.floor(totalMin / 60);
  const minutosRestantes = totalMin % 60;
  return `~${horas}h${minutosRestantes > 0 ? ` ${minutosRestantes}min` : ""}`;
}

// Mismo patron que ETAPAS_FICHA_RUC (ver empresas/page.js), para la
// consulta manual de una sola empresa -- ver core_scraper/adapter.py y
// app/jobs.py.
const ETAPAS_CONSULTA = {
  null: { porcentaje: 5, etiqueta: "Iniciando..." },
  iniciando_sesion: { porcentaje: 15, etiqueta: "Abriendo SUNAT..." },
  autenticando: { porcentaje: 30, etiqueta: "Iniciando sesion..." },
  leyendo_estado: { porcentaje: 50, etiqueta: "Leyendo estado del contribuyente..." },
  abriendo_buzon: { porcentaje: 65, etiqueta: "Abriendo el buzon..." },
  leyendo_mensajes: { porcentaje: 80, etiqueta: "Leyendo mensajes..." },
  descargando_documentos: { porcentaje: 92, etiqueta: "Descargando documentos nuevos..." },
};

function infoEtapaConsulta(etapa) {
  return ETAPAS_CONSULTA[etapa || "null"] || ETAPAS_CONSULTA.null;
}

// Compartido entre /empresas y /dashboard -- mismo boton de "Consultar
// todas" (encola una consulta espaciada para cada empresa del tenant, ver
// POST /empresas/consultar-todas) con su nube de progreso al pasar el
// mouse. El estado (polling de GET /empresas/estado-consultas) y el
// handler de click son responsabilidad de quien lo use, para que cada
// pagina decida que hacer al terminar (ej. refrescar su propia lista).
export default function BotonConsultarTodas({ onClick, consultando, estado, disabled }) {
  const enCurso = !!estado?.en_curso;
  const ocupado = consultando || enCurso;
  const porcentaje = enCurso && estado.total > 0 ? Math.round((estado.completados / estado.total) * 100) : 0;
  const empresasEnProgreso = estado?.empresas_en_progreso || [];
  // A pedido: mostrar CUAL empresa se esta consultando ahora mismo, no solo
  // el conteo -- sin esto el boton parece "colgado" en una tanda larga
  // (con muchas empresas, espaciadas ~45s entre si, puede tardar horas).
  const primeraEnProgreso = empresasEnProgreso[0];

  return (
    <div className="group relative">
      <button
        onClick={onClick}
        disabled={ocupado || disabled}
        className="flex max-w-xs items-center gap-1.5 rounded-lg border border-accent/30 bg-accent-light px-4 py-2 text-sm font-semibold text-accent transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
      >
        {ocupado ? (
          <Loader2 size={15} strokeWidth={1.5} className="shrink-0 animate-spin" />
        ) : (
          <Zap size={15} strokeWidth={1.5} className="shrink-0" />
        )}
        <span className="truncate">
          {enCurso
            ? primeraEnProgreso
              ? `${estado.completados}/${estado.total} · ${primeraEnProgreso.empresa_razon_social}`
              : `Consultando ${estado.completados}/${estado.total}`
            : consultando
            ? "Encolando..."
            : "Consultar todas"}
        </span>
      </button>

      {/* "Nube" con el avance -- aparece al pasar el mouse mientras hay una
          tanda en curso, sea porque el usuario la disparo desde aca o
          porque la disparo el chequeo automatico (11am/7:30pm) o el mismo
          boton desde la otra pagina (/empresas o /dashboard). */}
      {enCurso && (
        <div className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 w-72 -translate-x-1/2 opacity-0 transition-opacity duration-200 ease-out group-hover:opacity-100">
          <div className="absolute -top-1.5 left-1/2 h-3 w-3 -translate-x-1/2 rotate-45 rounded-sm bg-ink" />
          <div className="rounded-xl bg-ink px-3.5 py-3 text-white shadow-soft-lg">
            <div className="flex items-center justify-between text-xs font-semibold">
              <span>Consulta masiva en curso</span>
              <span>{porcentaje}%</span>
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/20">
              <div
                className="h-full rounded-full bg-accent transition-all duration-500"
                style={{ width: `${porcentaje}%` }}
              />
            </div>
            <p className="mt-2 text-[11px] text-slate-300">
              {estado.completados} completada{estado.completados === 1 ? "" : "s"}, {estado.pendientes + estado.en_progreso} en cola
              {estado.con_error > 0 ? `, ${estado.con_error} con error` : ""}
            </p>
            {empresasEnProgreso.length > 0 && (
              <div className="mt-2 space-y-1 border-t border-white/10 pt-2">
                {empresasEnProgreso.map((e) => (
                  <p key={e.empresa_id} className="truncate text-[11px] text-white">
                    <span className="font-semibold">{e.empresa_razon_social}</span>
                    <span className="text-slate-300"> — {infoEtapaConsulta(e.etapa).etiqueta}</span>
                  </p>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
