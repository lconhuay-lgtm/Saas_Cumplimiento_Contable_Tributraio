"use client";
import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, RefreshCw } from "lucide-react";
import { api } from "../../../../lib/api";
import { fechaHoraPeru, fechaPeru, hoyPeru, hoyPeruIso } from "../../../../lib/fechas";
import { ESTADOS_MES, textoPeriodo, textoRegimen, textoSoles } from "../../../../lib/liquidacion";
import DatosSunatLiquidacion from "./DatosSunatLiquidacion";
import GraficoDiario, { COLOR_REFERENCIA, SERIES } from "./GraficoDiario";

// Tablero de la Liquidacion en vivo de una empresa con el orden del boceto
// (Liquidación en vivo.html): fuente, hora de los datos y vencimiento; IGV,
// proyeccion y Renta; el mes dia a dia; "como se llega al monto" en lenguaje
// simple; alertas y comparacion con los 0621 anteriores; en el mes en curso,
// la proyeccion al cierre con su rango (Fase 6). Lo que llega en fases
// futuras (compras y detracciones, PDF y Excel) se muestra marcado. Al final, plegado, el detalle por casilla del 0621 para comparar
// con lo declarado (diferencias de mas de S/ 10, parametro 7.1).
const UMBRAL_DIFERENCIA = 10;
// Parametro 4.6: "Requiere atencion" si el IGV sube 15 % o mas frente al mismo mes del ano anterior.
const ALZA_DE_ATENCION = 0.15;

const CAJA = "rounded-xl border border-slate-200 bg-white p-5";
const BOTON = "flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed";

function mayuscula(texto) {
  return texto ? texto[0].toUpperCase() + texto.slice(1) : texto;
}

function diasHasta(fecha) {
  return Math.round((Date.parse(fecha) - Date.parse(hoyPeruIso())) / 86400000);
}

function diaMes(fecha, opciones = {}) {
  return fechaPeru(fecha, { day: "2-digit", month: "2-digit", ...opciones });
}

function textoActualizado(instante) {
  const dia = hoyPeruIso(new Date(instante)) === hoyPeruIso() ? "hoy" : diaMes(instante);
  return `${dia}, ${fechaHoraPeru(instante, { hour: "numeric", minute: "2-digit" })}`;
}

function porcentaje(p) {
  return `${+(p * 100).toFixed(2)} %`;
}

function Etiqueta({ tono, children }) {
  const tonos = {
    azul: "bg-accent-light text-accent",
    gris: "bg-slate-100 text-slate-600",
    ambar: "bg-amber-50 text-amber-800",
    verde: "bg-emerald-50 text-emerald-700",
  };
  return <span className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${tonos[tono]}`}>{children}</span>;
}

function Tarjeta({ titulo, valor, tonoValor = "text-ink", borde = "border-slate-200", children }) {
  return (
    <div className={`rounded-xl border ${borde} bg-white p-5`}>
      <div className="text-sm text-slate-600">{titulo}</div>
      <div className={`mt-1 font-heading text-4xl font-bold tabular-nums ${tonoValor}`}>{valor}</div>
      <div className="mt-2 space-y-0.5 text-xs text-slate-600">{children}</div>
    </div>
  );
}

function Pronto({ fase }) {
  return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-slate-500">{fase}</span>;
}

function ComoSeLlega({ lineas, casillas }) {
  const noGravadas = casillas["105"] + casillas["109"];
  return (
    <div className={CAJA}>
      <h3 className="font-heading text-lg font-bold text-ink">Cómo se llega al monto</h3>
      <ul className="mt-2">
        {lineas.map((l) => {
          const resultado = l.tipo === "total" || l.tipo === "subtotal";
          const grande = l.tipo === "total";
          return (
            <li key={l.concepto} className={`flex items-start justify-between gap-4 border-t py-3 first:border-t-0 ${grande ? "border-slate-300" : "border-slate-100"}`}>
              <div className="min-w-0">
                <div className={grande ? "font-heading text-lg font-bold text-ink" : "font-semibold text-ink"}>
                  {resultado ? "= " : l.signo < 0 ? "− " : ""}
                  {l.concepto}
                </div>
                {l.fuente && <div className="mt-0.5 text-xs text-slate-500">{l.fuente}</div>}
                {l.nota && <div className="mt-0.5 text-xs text-amber-700">{l.nota}</div>}
              </div>
              <div className={`whitespace-nowrap tabular-nums ${grande ? "font-heading text-2xl font-bold text-ink" : "font-semibold text-ink"}`}>
                {l.signo < 0 ? "− " : ""}
                {textoSoles(l.monto)}
              </div>
            </li>
          );
        })}
      </ul>
      <div className="mt-2 rounded-lg bg-slate-50 px-3 py-2.5 text-xs text-slate-600">
        <span className="font-semibold text-ink">Aparte (información):</span> ventas no gravadas {textoSoles(noGravadas)} (no suman
        IGV, sí suman a la Renta)
        {casillas["106"] ? ` · exportaciones ${textoSoles(casillas["106"])}` : ""}.
      </div>
    </div>
  );
}

// Arriba lo que "Requiere atencion" (4.6, rojo); debajo los avisos del calculo (datos que faltan, reglas aplicadas).
function Alertas({ atencion, avisos }) {
  return (
    <div className={`rounded-xl border bg-white p-5 ${atencion.length ? "border-red-200" : "border-slate-200"}`}>
      <h3 className="font-heading text-lg font-bold text-ink">Alertas</h3>
      {!atencion.length && !avisos.length && <p className="mt-2 text-sm text-slate-500">Sin alertas para este periodo.</p>}
      <ul className="mt-3 space-y-2">
        {atencion.map((a) => (
          <li key={a} className="rounded-lg bg-red-50 px-3 py-2.5 text-sm font-semibold text-red-700">{a}</li>
        ))}
        {avisos.map((a) => (
          <li key={a} className="rounded-lg bg-slate-50 px-3 py-2.5 text-sm text-slate-700">{a}</li>
        ))}
      </ul>
      <p className="mt-3 flex items-center gap-2 text-xs text-slate-500">
        Resumen diario a las 8:00 a.m. por correo y en la plataforma <Pronto fase="Fase 7" />
      </p>
    </div>
  );
}

function Comparacion({ filas }) {
  return (
    <div className={CAJA}>
      <h3 className="font-heading text-lg font-bold text-ink">Comparación</h3>
      <p className="mt-0.5 text-xs text-slate-500">IGV a pagar de los 0621 presentados.</p>
      <ul className="mt-3 space-y-2 text-sm">
        {filas.map((f) => (
          <li key={f.concepto} className="flex justify-between gap-3">
            <span className="text-slate-600">{f.concepto}</span>
            <span className="font-semibold tabular-nums text-ink">{f.igv === null ? "Sin 0621" : textoSoles(f.igv)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ComprasPronto({ compras }) {
  const grupos = ["Detracción pagada", "Con plazo para depositar", "No depositada · vencida", "Por verificar", "Excluidos a mano"];
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 font-heading text-lg font-bold text-ink">
          Compras, detracciones y crédito fiscal <Pronto fase="Fase 5 · enero" />
        </h3>
        <button disabled className={`${BOTON} bg-slate-100 text-slate-400`}>Revisar compras</button>
      </div>
      <p className="mt-1 text-sm text-slate-600">
        Aquí se cruzarán {compras !== null ? `las ${compras} compras del mes` : "las compras del mes"} con los depósitos de
        detracción, y el responsable decidirá qué se incluye o excluye del crédito.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {grupos.map((g) => (
          <div key={g} className="rounded-lg bg-slate-50 p-3">
            <div className="text-xs font-semibold text-slate-500">{g}</div>
            <div className="mt-1 font-heading text-xl font-bold text-slate-300">—</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TablaLineas({ titulo, lineas, conDeclarado }) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
          <tr className="border-b border-slate-200">
            <th className="w-16 py-2 pr-2">Casilla</th>
            <th className="py-2 pr-2">{titulo}</th>
            <th className="py-2 pr-2 text-right">Estimado</th>
            {conDeclarado && <th className="py-2 pr-2 text-right">Declarado</th>}
            <th className="hidden py-2 pl-3 md:table-cell">De dónde sale</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {lineas.map((l, i) => {
            const fuerte = l.tipo === "subtotal" || l.tipo === "total";
            const diferencia = conDeclarado && l.declarado !== null && l.monto !== null && Math.abs(l.monto - l.declarado) > UMBRAL_DIFERENCIA;
            return (
              <tr key={`${l.casilla}-${i}`} className={l.tipo === "total" ? "bg-slate-50" : ""}>
                <td className="py-2 pr-2 font-mono text-xs text-slate-500">{l.casilla || ""}</td>
                <td className={`py-2 pr-2 ${fuerte ? "font-bold text-ink" : "text-slate-700"}`}>{l.concepto}</td>
                <td className={`whitespace-nowrap py-2 pr-2 text-right tabular-nums ${fuerte ? "font-bold text-ink" : "text-slate-700"}`}>
                  {l.monto === null ? "—" : `${l.signo < 0 && l.monto ? "− " : ""}${textoSoles(l.monto)}`}
                </td>
                {conDeclarado && (
                  <td className={`whitespace-nowrap py-2 pr-2 text-right tabular-nums ${diferencia ? "font-bold text-amber-700" : "text-slate-500"}`}>
                    {l.declarado === null ? "—" : textoSoles(l.declarado)}
                  </td>
                )}
                <td className="hidden py-2 pl-3 text-xs text-slate-500 md:table-cell">{l.fuente || ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DetalleCasillas({ calculo }) {
  const conDeclarado = Boolean(calculo.declarado);
  const diferencias = conDeclarado
    ? [...calculo.lineas_igv, ...calculo.lineas_siguiente, ...calculo.lineas_renta].filter(
      (l) => l.declarado !== null && l.monto !== null && Math.abs(l.monto - l.declarado) > UMBRAL_DIFERENCIA,
    ).length
    : 0;
  return (
    <details key={calculo.periodo} open={conDeclarado} className={`${CAJA} group`}>
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2">
        <span className="font-heading text-lg font-bold text-ink">Detalle por casilla del 0621</span>
        <span className="text-xs text-slate-500">
          {conDeclarado
            ? diferencias
              ? `${diferencias} casilla(s) difieren en más de S/ ${UMBRAL_DIFERENCIA} de lo declarado`
              : "Cuadra con lo declarado"
            : "Para comparar con el 0621 cuando se presente"}
          <span className="ml-2 text-accent group-open:hidden">Ver</span>
          <span className="ml-2 hidden text-accent group-open:inline">Ocultar</span>
        </span>
      </summary>
      <h4 className="mt-4 text-sm font-bold text-ink">IGV</h4>
      <TablaLineas titulo="Concepto" lineas={calculo.lineas_igv} conDeclarado={conDeclarado} />
      <h4 className="mt-5 text-sm font-bold text-ink">Pasa al mes siguiente</h4>
      <TablaLineas titulo="Concepto" lineas={calculo.lineas_siguiente} conDeclarado={conDeclarado} />
      <h4 className="mt-5 text-sm font-bold text-ink">Renta</h4>
      <TablaLineas titulo="Concepto" lineas={calculo.lineas_renta} conDeclarado={conDeclarado} />
      <p className="mt-4 text-xs text-slate-500">
        Estimado en soles enteros, como el 0621. Las ventas y compras salen de la propuesta del SIRE: si el registro final
        excluye o agrega comprobantes, el monto declarado puede cambiar.
      </p>
    </details>
  );
}

export default function TableroLiquidacion({ empresaId, periodo, periodos, onPeriodo, version, lecturas }) {
  const [calculo, setCalculo] = useState(null);
  const [serie, setSerie] = useState(null);
  const [error, setError] = useState("");
  const [revisando, setRevisando] = useState(false);

  async function marcarRevisado() {
    setRevisando(true);
    try {
      const revisado = await api.marcarRevisadoLiquidacion(empresaId, periodo);
      setCalculo((actual) => ({ ...actual, revisado }));
    } catch (err) {
      setError(err.message);
    } finally {
      setRevisando(false);
    }
  }

  useEffect(() => {
    let vigente = true;
    setCalculo(null);
    setSerie(null);
    api.verCalculoLiquidacion(empresaId, periodo)
      .then((data) => vigente && (setCalculo(data), setError("")))
      .catch((err) => vigente && setError(err.message));
    api.verSerieLiquidacion(empresaId, periodo)
      .then((data) => vigente && setSerie(data.puntos))
      .catch(() => vigente && setSerie([]));
    return () => {
      vigente = false;
    };
  }, [empresaId, periodo, version]);

  const hoy = hoyPeru();
  const mesActual = hoyPeruIso().slice(0, 7);
  const enCurso = periodo === mesActual;
  const mes = textoPeriodo(periodo).split(" ")[0];
  const [anio, numeroMes] = periodo.split("-").map(Number);
  const diasDelMes = new Date(anio, numeroMes, 0).getDate();
  const leyendo = lecturas.pidiendo || lecturas.datos?.en_curso;

  const controles = (
    <div className="flex flex-wrap items-end gap-2">
      <label className="text-xs font-semibold text-slate-500">
        Periodo
        <select
          value={periodo}
          onChange={(e) => onPeriodo(e.target.value)}
          className="mt-1 block rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-normal text-ink focus:border-accent focus:outline-none"
        >
          {periodos.map((p) => (
            <option key={p} value={p}>{mayuscula(textoPeriodo(p))}{p === mesActual ? " (en curso)" : ""}</option>
          ))}
        </select>
      </label>
      <button disabled title="Llega en la Fase 7" className={`${BOTON} border border-slate-200 bg-white text-slate-400`}>PDF</button>
      <button disabled title="Llega en la Fase 7" className={`${BOTON} border border-slate-200 bg-white text-slate-400`}>Excel</button>
      {lecturas.datos?.puede_leer && (
        <button onClick={lecturas.leer} disabled={leyendo} className={`${BOTON} bg-accent font-bold text-white hover:opacity-90 disabled:opacity-60`}>
          {leyendo ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
          {leyendo ? "Leyendo SUNAT..." : "Actualizar ahora"}
        </button>
      )}
      {calculo?.puede_revisar && (
        <button onClick={marcarRevisado} disabled={revisando}
          className={`${BOTON} border border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-50 disabled:opacity-60`}>
          {revisando ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} />}
          Marcar como revisado
        </button>
      )}
      {calculo?.revisado && (
        <span className="self-center text-xs text-slate-500">
          Revisado{calculo.revisado.usuario_nombre ? ` por ${calculo.revisado.usuario_nombre}` : ""} el{" "}
          {fechaHoraPeru(calculo.revisado.fecha, { day: "2-digit", month: "2-digit", hour: "numeric", minute: "2-digit" })}
        </span>
      )}
    </div>
  );

  if (!calculo) {
    return (
      <div className="mt-5">
        {controles}
        {error ? (
          <div className="mt-4 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>
        ) : (
          <p className="mt-6 text-sm text-slate-500">Calculando...</p>
        )}
      </div>
    );
  }

  const c = calculo.casillas;
  const saldo = calculo.saldo_a_favor > 0;
  const montoMes = saldo ? calculo.saldo_a_favor : calculo.igv_por_pagar;
  const declaradoIgv = calculo.lineas_igv.find((l) => l.casilla === "681")?.declarado;
  const [mismoMes, , promedio] = calculo.comparacion;
  const textoMismoMes = mismoMes.periodo ? textoPeriodo(mismoMes.periodo) : "";
  // Proyeccion al cierre (Fase 6): solo el mes en curso sin 0621 y con historial o datos del mes.
  const proy = calculo.proyeccion && !calculo.proyeccion.sin_base ? calculo.proyeccion : null;
  const alza = mismoMes.igv ? ((proy ? proy.por_pagar : c["681"]) - mismoMes.igv) / mismoMes.igv : null;
  const requiereAtencion = alza !== null && alza >= ALZA_DE_ATENCION;
  const lecturaSire = calculo.fechas.sire;

  const vence = calculo.vence;
  const estadoMes = ESTADOS_MES[calculo.estado_mes] || ESTADOS_MES.en_curso;
  const tonoEstado = { conciliado: "verde", con_diferencias: "ambar", declarado: "azul" }[calculo.estado_mes];

  return (
    <div className="mt-4 space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Etiqueta tono="azul">Fuente: SIRE · propuesta</Etiqueta>
        <Etiqueta tono={lecturaSire ? "gris" : "ambar"}>
          {lecturaSire ? `Actualizado ${textoActualizado(lecturaSire)}` : "Falta leer el SIRE del mes"}
        </Etiqueta>
        {calculo.declarado ? (
          <Etiqueta tono={tonoEstado || "azul"}>
            <CheckCircle2 size={13} />
            {estadoMes.texto} · 0621 presentado
            {calculo.declarado.fecha_presentacion ? ` el ${fechaPeru(calculo.declarado.fecha_presentacion, { timeZone: "UTC" })}` : ""}
            {` (orden ${calculo.declarado.num_orden})`}
          </Etiqueta>
        ) : vence ? (
          <Etiqueta tono="ambar">
            Vence el {fechaPeru(vence, { timeZone: "UTC" })} ·{" "}
            {diasHasta(vence) < 0 ? "venció" : diasHasta(vence) === 0 ? "hoy" : `en ${diasHasta(vence)} días`}
          </Etiqueta>
        ) : (
          <Etiqueta tono="gris">Sin vencimiento en el cronograma</Etiqueta>
        )}
        {lecturas.datos?.en_curso && (
          <Etiqueta tono="azul">
            <Loader2 size={13} className="animate-spin" />
            Leyendo datos de SUNAT
          </Etiqueta>
        )}
      </div>

      {controles}
      {lecturas.error && <div className="rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{lecturas.error}</div>}

      <div className="grid gap-4 lg:grid-cols-3">
        <Tarjeta
          titulo={`${saldo ? "Saldo a favor" : "IGV a pagar"} ${enCurso ? `si ${mes} cerrara hoy` : `de ${mes}`}`}
          valor={textoSoles(montoMes)}
          tonoValor={saldo ? "text-emerald-700" : "text-ink"}
        >
          <div>{lecturaSire ? `con ventas y compras al ${diaMes(lecturaSire)}` : "falta leer el SIRE del mes"}</div>
          {saldo && <div>pasa al mes siguiente</div>}
          {declaradoIgv !== null && declaradoIgv !== undefined && (
            <div className="font-semibold text-emerald-700">Declarado en el 0621: {textoSoles(declaradoIgv)}</div>
          )}
        </Tarjeta>
        <Tarjeta
          titulo={proy?.saldo_a_favor ? "Saldo a favor proyectado al cierre" : "IGV proyectado al cierre"}
          valor={!enCurso ? textoSoles(montoMes) : proy ? textoSoles(proy.saldo_a_favor || proy.igv) : "—"}
          tonoValor={
            enCurso && !proy ? "text-slate-300" : proy?.saldo_a_favor ? "text-emerald-700" : requiereAtencion ? "text-red-700" : "text-ink"
          }
          borde={requiereAtencion ? "border-red-200" : "border-slate-200"}
        >
          <div>
            {!enCurso
              ? "El mes ya cerró: es el monto final"
              : !proy
                ? "Sin historial ni datos del mes para proyectar"
                : proy.solo_historial
                  ? "Basado en el historial (los primeros días del mes)"
                  : `Al ritmo del mes (pesa ${Math.round(proy.peso_del_mes * 100)} %) y el historial`}
          </div>
          {proy && (
            <div className="text-slate-400">
              Orientativa: se aleja si las ventas o compras se concentran a fin de mes
            </div>
          )}
          {proy && (
            <div>
              {proy.maximo > 0
                ? `Rango: ${textoSoles(proy.minimo)} a ${textoSoles(proy.maximo)}`
                : "En todos los escenarios queda saldo a favor"}
            </div>
          )}
          {alza !== null && (
            <div className={`font-semibold ${requiereAtencion ? "text-red-700" : "text-slate-700"}`}>
              {alza >= 0 ? "+" : ""}
              {Math.round(alza * 100)} % frente a {textoMismoMes} ({textoSoles(mismoMes.igv)})
            </div>
          )}
          {alza === null && promedio.igv !== null && <div>Promedio de 12 meses: {textoSoles(promedio.igv)}</div>}
        </Tarjeta>
        <Tarjeta titulo="Pago a cuenta de Renta" valor={calculo.renta_por_pagar === null ? "—" : textoSoles(calculo.renta_por_pagar)}>
          <div title={calculo.renta_regla}>
            {calculo.renta_porcentaje === null
              ? "Falta el régimen: confírmalo en Configuración"
              : `${porcentaje(calculo.renta_porcentaje)} de ingresos netos ${textoSoles(c["301"])} (${textoRegimen(calculo.regimen)})`}
          </div>
          {c["317"] > 0 && <div>menos pagos ya hechos {textoSoles(c["317"])}</div>}
        </Tarjeta>
      </div>

      <div className={CAJA}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="font-heading text-lg font-bold text-ink">Cómo va el mes, día a día</h3>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
            {SERIES.map((s) => (
              <span key={s.clave} className="flex items-center gap-1.5">
                <span className="h-0.5 w-4 rounded" style={{ backgroundColor: s.color }} />
                {s.texto}
              </span>
            ))}
            {mismoMes.igv !== null && (
              <span className="flex items-center gap-1.5">
                <span className="w-4 border-t-2 border-dashed" style={{ borderColor: COLOR_REFERENCIA }} />
                Declarado {textoMismoMes}
              </span>
            )}
            {proy && (
              <span className="flex items-center gap-1.5">
                <span className="w-4 border-t-2 border-dashed border-slate-400" />
                Proyección
              </span>
            )}
          </div>
        </div>
        {serie === null ? (
          <p className="mt-6 text-sm text-slate-500">Armando el gráfico...</p>
        ) : (
          <GraficoDiario
            puntos={serie}
            diasDelMes={diasDelMes}
            referencia={mismoMes.igv ? { texto: `Declarado ${textoMismoMes}`, monto: mismoMes.igv } : null}
            hoy={enCurso ? hoy.dia : null}
            proyeccion={proy}
          />
        )}
        <p className="mt-2 text-xs text-slate-500">
          Cada día se rehace con la fecha de emisión de los comprobantes de la propuesta del SIRE.
          {proy ? " En punteado, la proyección al cierre." : ""}
        </p>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <ComoSeLlega lineas={calculo.lineas_monto} casillas={c} />
        <div className="space-y-5">
          <Alertas atencion={calculo.atencion} avisos={calculo.avisos} />
          <Comparacion filas={calculo.comparacion} />
        </div>
      </div>

      <ComprasPronto compras={lecturas.datos?.resumen?.compras?.cantidad ?? null} />

      <DetalleCasillas calculo={calculo} />

      <DatosSunatLiquidacion periodo={periodo} lecturas={lecturas} />
    </div>
  );
}
