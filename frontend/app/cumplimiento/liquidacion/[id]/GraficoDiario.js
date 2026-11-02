"use client";
import { useState } from "react";
import { textoSoles } from "../../../../lib/liquidacion";

// "Como va el mes, dia a dia" del boceto: IGV de ventas, credito fiscal e IGV
// a pagar acumulados de cada dia del periodo (backend: serie_diaria), con el
// IGV declarado del mismo mes del ano anterior como referencia. SVG a mano:
// para tres lineas no hace falta una libreria de graficos.
const ANCHO = 1000;
const ALTO = 300;
const IZQ = 52;
const DER = 12;
const ARRIBA = 26;
const ABAJO = 26;

export const SERIES = [
  { clave: "ventas", texto: "IGV de ventas", color: "#2563eb" },
  { clave: "credito", texto: "IGV de compras (crédito)", color: "#f59e0b" },
  { clave: "por_pagar", texto: "IGV a pagar", color: "#0f172a" },
];
export const COLOR_REFERENCIA = "#dc2626";

// Tope "redondo" del eje para 4 lineas guia (1, 2, 2.5 o 5 por 10^n cada una).
function topeDelEje(valor) {
  if (valor <= 0) return 1000;
  const paso = valor / 4;
  const potencia = 10 ** Math.floor(Math.log10(paso));
  return [1, 2, 2.5, 5, 10].find((m) => m * potencia >= paso) * potencia * 4;
}

function textoEje(v) {
  return v >= 1000 ? `${+(v / 1000).toFixed(1)}k` : String(v);
}

export default function GraficoDiario({ puntos, diasDelMes, referencia, hoy }) {
  const [activo, setActivo] = useState(null);
  if (!puntos.length) {
    return <p className="mt-6 text-sm text-slate-500">Falta leer el SIRE de este periodo para armar el gráfico.</p>;
  }

  const tope = topeDelEje(Math.max(...puntos.flatMap((p) => SERIES.map((s) => p[s.clave])), referencia?.monto || 0));
  const x = (dia) => IZQ + ((dia - 1) / Math.max(diasDelMes - 1, 1)) * (ANCHO - IZQ - DER);
  const y = (v) => ARRIBA + (1 - Math.max(v, 0) / tope) * (ALTO - ARRIBA - ABAJO);
  const dia = (p) => Number(p.fecha.slice(8, 10));
  const marcas = [1, 5, 10, 15, 20, 25, diasDelMes].filter((d, i, a) => d <= diasDelMes && a.indexOf(d) === i);
  const punto = activo === null ? null : puntos[activo];

  return (
    <div className="relative mt-3">
      <svg viewBox={`0 0 ${ANCHO} ${ALTO}`} className="w-full" role="img" aria-label="IGV del mes día a día">
        {[0, 1, 2, 3, 4].map((i) => {
          const v = (tope / 4) * i;
          return (
            <g key={i}>
              <line x1={IZQ} x2={ANCHO - DER} y1={y(v)} y2={y(v)} stroke="#e2e8f0" strokeWidth="1" />
              <text x={IZQ - 10} y={y(v) + 4} textAnchor="end" fontSize="12" fill="#64748b">{textoEje(v)}</text>
            </g>
          );
        })}
        {marcas.map((d) => (
          <text key={d} x={x(d)} y={ALTO - 6} textAnchor="middle" fontSize="12" fill="#94a3b8">{d}</text>
        ))}

        {referencia && (
          <g>
            <line x1={IZQ} x2={ANCHO - DER} y1={y(referencia.monto)} y2={y(referencia.monto)}
              stroke={COLOR_REFERENCIA} strokeWidth="1.5" strokeDasharray="4 4" />
            {/* Debajo de la linea y con borde blanco, para que no se mezcle con las series. */}
            <text x={ANCHO - DER} y={y(referencia.monto) + 17} textAnchor="end" fontSize="12" fill={COLOR_REFERENCIA}
              stroke="white" strokeWidth="4" paintOrder="stroke" strokeLinejoin="round">
              {referencia.texto}: {textoSoles(referencia.monto)}
            </text>
          </g>
        )}

        {hoy && hoy <= diasDelMes && (
          <g>
            <line x1={x(hoy)} x2={x(hoy)} y1={ARRIBA - 8} y2={ALTO - ABAJO} stroke="#94a3b8" strokeWidth="1" />
            <text x={x(hoy)} y={ARRIBA - 12} textAnchor="middle" fontSize="12" fontWeight="600" fill="#334155">Hoy</text>
          </g>
        )}

        {SERIES.map((s) => (
          <polyline key={s.clave} fill="none" stroke={s.color} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round"
            points={puntos.map((p) => `${x(dia(p))},${y(p[s.clave])}`).join(" ")} />
        ))}

        {punto && (
          <g>
            <line x1={x(dia(punto))} x2={x(dia(punto))} y1={ARRIBA} y2={ALTO - ABAJO} stroke="#cbd5e1" strokeWidth="1" />
            {SERIES.map((s) => (
              <circle key={s.clave} cx={x(dia(punto))} cy={y(punto[s.clave])} r="4.5" fill="white" stroke={s.color} strokeWidth="2.5" />
            ))}
          </g>
        )}

        {puntos.map((p, i) => (
          <rect key={p.fecha} x={x(dia(p)) - (ANCHO - IZQ - DER) / diasDelMes / 2} y={ARRIBA}
            width={(ANCHO - IZQ - DER) / diasDelMes} height={ALTO - ARRIBA - ABAJO} fill="transparent"
            onMouseEnter={() => setActivo(i)} onMouseLeave={() => setActivo(null)} />
        ))}
      </svg>

      {punto && (
        <div
          className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-soft-lg"
          style={{ left: `${Math.min(Math.max((x(dia(punto)) / ANCHO) * 100, 12), 88)}%` }}
        >
          <div className="font-semibold text-ink">Al {punto.fecha.slice(8, 10)}/{punto.fecha.slice(5, 7)}</div>
          {SERIES.map((s) => (
            <div key={s.clave} className="mt-0.5 flex items-center justify-between gap-4">
              <span className="flex items-center gap-1.5 text-slate-600">
                <span className="h-0.5 w-3" style={{ backgroundColor: s.color }} />
                {s.texto}
              </span>
              <span className="font-semibold tabular-nums text-ink">{textoSoles(punto[s.clave])}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
