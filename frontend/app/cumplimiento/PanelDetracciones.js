"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, Download, Loader2, Search, SearchCheck } from "lucide-react";
import { api } from "../../lib/api";
import { descargarCsv, periodoPorDefecto } from "./utilidades";

// Mismos criterios que la "Consulta de Pago de Detracciones" de SUNAT.
const TIPOS_CUENTA = [
  { id: "1", label: "Cuenta de Detracciones Convencional" },
  { id: "2", label: "Cuenta de Detracciones Especial IVAP" },
  { id: "3", label: "Cuenta-Ley N° 30737" },
  { id: "todas", label: "Todas las cuentas" },
];
const NOMBRE_CUENTA = { 1: "Convencional", 2: "Especial IVAP", 3: "Ley 30737" };
const TIPOS_PAGO = [
  { id: "pagosIndividuales", label: "Pagos individuales" },
  { id: "pagosMasivos", label: "Pagos masivos" },
  { id: "pagosTransPasajeros", label: "Pagos transporte de pasajeros" },
  { id: "todos", label: "Todos los tipos de pago" },
];

// Anexos del SPOT (Res. 183-2004/SUNAT y modificatorias).
const BIEN_SERVICIO = {
  "001": "Azucar y melaza de caña", "003": "Alcohol etilico", "004": "Recursos hidrobiologicos",
  "005": "Maiz amarillo duro", "007": "Caña de azucar", "008": "Madera", "009": "Arena y piedra",
  "010": "Residuos, subproductos y desechos", "011": "Bienes gravados por renuncia a la exoneracion",
  "012": "Intermediacion laboral y tercerizacion", "013": "Animales vivos", "014": "Carnes y despojos comestibles",
  "015": "Abonos, cueros y pieles de origen animal", "016": "Aceite de pescado", "017": "Harina y pellets de pescado",
  "019": "Arrendamiento de bienes muebles", "020": "Mantenimiento y reparacion de bienes muebles",
  "021": "Movimiento de carga", "022": "Otros servicios empresariales", "023": "Leche", "024": "Comision mercantil",
  "025": "Fabricacion de bienes por encargo", "026": "Servicio de transporte de personas",
  "027": "Servicio de transporte de bienes", "028": "Transporte de pasajeros", "030": "Contratos de construccion",
  "031": "Oro gravado con el IGV", "032": "Paprika y otros frutos capsicum", "034": "Minerales metalicos no auriferos",
  "035": "Bienes exonerados del IGV", "036": "Oro y minerales metalicos exonerados", "037": "Demas servicios gravados con el IGV",
  "039": "Minerales no metalicos", "040": "Bien inmueble gravado con IGV", "041": "Plomo",
};
const OPERACION = {
  "01": "Venta de bienes o prestacion de servicios", "02": "Retiro de bienes gravado con el IGV",
  "03": "Traslado de bienes fuera del centro de produccion", "04": "Venta a traves de la Bolsa de Productos",
  "05": "Venta de bienes exonerada del IGV",
};
const COMPROBANTE = { "01": "Factura", "03": "Boleta", "07": "Nota de credito", "08": "Nota de debito", "12": "Ticket" };
const ETAPAS = {
  pendiente: "En cola, empieza en unos segundos...",
  autenticando: "Entrando a SUNAT (Mis Declaraciones y Pagos)...",
  abriendo_detracciones: "Abriendo la Consulta de Pago de Detracciones...",
  leyendo_detracciones: "Leyendo los depositos...",
};
const EN_CURSO = ["pendiente", "en_progreso"];
const CLAVE_EMPRESA = "cumplimiento:detracciones:empresa";

const soles = new Intl.NumberFormat("es-PE", { style: "currency", currency: "PEN" });

function isoLocal(d) {
  return d.toLocaleDateString("en-CA");
}

function fechaCorta(iso) {
  if (!iso) return "—";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

function nombreBien(codigo) {
  return BIEN_SERVICIO[codigo] ? `${codigo} - ${BIEN_SERVICIO[codigo]}` : codigo || "—";
}

export default function PanelDetracciones({ empresaInicial = null }) {
  const hoy = new Date();
  const hace30 = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() - 29);
  const porDefecto = periodoPorDefecto();

  const [empresas, setEmpresas] = useState([]);
  const [empresaId, setEmpresaId] = useState("");
  const [modo, setModo] = useState("fechas");
  const [desde, setDesde] = useState(isoLocal(hace30));
  const [hasta, setHasta] = useState(isoLocal(hoy));
  const [periodo, setPeriodo] = useState(`${porDefecto.anio}-${String(porDefecto.mes).padStart(2, "0")}`);
  const [tipoCuenta, setTipoCuenta] = useState("1");
  const [tipoPago, setTipoPago] = useState("pagosIndividuales");
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [rol, setRol] = useState("todos");
  const [texto, setTexto] = useState("");
  const busquedaSeguida = useRef(null);

  useEffect(() => {
    api
      .listarEmpresas()
      .then((lista) => {
        const ordenadas = [...lista].sort((a, b) => a.razon_social.localeCompare(b.razon_social));
        setEmpresas(ordenadas);
        let guardada = null;
        try {
          guardada = localStorage.getItem(CLAVE_EMPRESA);
        } catch {}
        const inicial = [empresaInicial, guardada].find((id) => id && ordenadas.some((e) => e.id === id));
        setEmpresaId(inicial || ordenadas.find((e) => e.activo)?.id || "");
      })
      .catch((err) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtros = useMemo(
    () => ({
      ...(modo === "periodo" ? { periodo } : { fecha_desde: desde, fecha_hasta: hasta }),
      tipo_cuenta: tipoCuenta === "todas" ? "" : tipoCuenta,
      tipo_pago: tipoPago === "todos" ? "" : tipoPago,
    }),
    [modo, periodo, desde, hasta, tipoCuenta, tipoPago]
  );

  async function cargar({ silencioso = false } = {}) {
    if (!empresaId) return;
    if (!silencioso) setCargando(true);
    try {
      const data = await api.obtenerDetracciones(empresaId, filtros);
      setDatos(data);
      setError("");
      const b = data.busqueda;
      // Avisar cuando termina la busqueda que se estaba siguiendo.
      if (b && busquedaSeguida.current === b.id && !EN_CURSO.includes(b.estado)) {
        busquedaSeguida.current = null;
        if (b.estado === "completado") setAviso(`Busqueda terminada: SUNAT devolvio ${b.depositos_leidos} deposito(s).`);
        else setError(`La busqueda en SUNAT fallo: ${b.error || "error desconocido"}`);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setCargando(false);
    }
  }

  useEffect(() => {
    if (!empresaId) return;
    try {
      localStorage.setItem(CLAVE_EMPRESA, empresaId);
    } catch {}
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empresaId, filtros]);

  const buscandoEnSunat = !!datos?.busqueda && EN_CURSO.includes(datos.busqueda.estado);
  useEffect(() => {
    if (!buscandoEnSunat) return;
    const t = setInterval(() => cargar({ silencioso: true }), 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buscandoEnSunat, empresaId, filtros]);

  async function buscarEnSunat() {
    setEnviando(true);
    setError("");
    setAviso("");
    try {
      const job = await api.consultarDetracciones(empresaId, {
        ...(modo === "periodo" ? { periodo } : { fecha_desde: desde, fecha_hasta: hasta }),
        tipos_cuenta: tipoCuenta === "todas" ? ["1", "2", "3"] : [tipoCuenta],
        tipos_pago: tipoPago === "todos" ? TIPOS_PAGO.filter((t) => t.id !== "todos").map((t) => t.id) : [tipoPago],
      });
      busquedaSeguida.current = job.id;
      setDatos((d) => (d ? { ...d, busqueda: job } : d));
    } catch (err) {
      setError(err.message);
    } finally {
      setEnviando(false);
    }
  }

  const depositos = datos?.depositos || [];
  const esRecibido = (d) => d.ruc_proveedor === datos?.ruc;

  const resumen = useMemo(() => {
    const r = { recibido: 0, nRecibido: 0, pagado: 0, nPagado: 0 };
    depositos.forEach((d) => {
      if (esRecibido(d)) {
        r.recibido += d.monto;
        r.nRecibido += 1;
      } else {
        r.pagado += d.monto;
        r.nPagado += 1;
      }
    });
    return r;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [depositos]);

  const visibles = useMemo(() => {
    const q = texto.trim().toLowerCase();
    return depositos.filter((d) => {
      if (rol === "recibidos" && !esRecibido(d)) return false;
      if (rol === "pagados" && esRecibido(d)) return false;
      if (!q) return true;
      return [d.proveedor, d.adquiriente, d.ruc_proveedor, d.doc_adquiriente, d.num_constancia, `${d.serie}-${d.numero}`]
        .some((v) => (v || "").toLowerCase().includes(q));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [depositos, rol, texto]);

  function exportarCsv() {
    descargarCsv(
      `detracciones_${datos?.ruc || ""}.csv`,
      ["Tipo", "Tipo de cuenta", "N° cuenta", "Fecha pago", "Periodo", "Comprobante", "Constancia", "RUC proveedor",
        "Proveedor", "Doc. adquiriente", "Adquiriente", "Operacion", "Bien o servicio", "Monto", "N° pago detracciones", "Origen"],
      visibles.map((d) => [
        esRecibido(d) ? "Recibido" : "Pagado", NOMBRE_CUENTA[d.tipo_cuenta] || d.tipo_cuenta, d.num_cuenta, fechaCorta(d.fecha_pago),
        d.periodo, `${COMPROBANTE[d.tipo_comprobante] || d.tipo_comprobante} ${d.serie}-${d.numero}`, d.num_constancia,
        d.ruc_proveedor, d.proveedor, d.doc_adquiriente, d.adquiriente, OPERACION[d.tipo_operacion] || d.tipo_operacion,
        nombreBien(d.tipo_bien), d.monto.toFixed(2), d.num_pago, d.origen,
      ])
    );
  }

  const campo = "rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-ink focus:border-accent focus:outline-none";
  const etiqueta = "flex flex-col gap-1 text-xs font-semibold text-slate-500";
  const busqueda = datos?.busqueda;

  return (
    <>
      <p className="mt-5 max-w-3xl text-sm text-slate-600">
        Depositos de detracciones (SPOT) de cada empresa, buscados directamente en SUNAT en "Consulta de Pago de
        Detracciones": los que tus clientes depositaron en tu cuenta del Banco de la Nacion y los que tu pagaste a tus
        proveedores. Elige la empresa y los criterios, y presiona "Buscar en SUNAT". Todo lo encontrado queda guardado.
      </p>

      <div className="surface-card mt-5 p-5">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <label className={`${etiqueta} md:col-span-2`}>
            Empresa
            <select value={empresaId} onChange={(e) => { setEmpresaId(e.target.value); setAviso(""); }} className={campo}>
              {!empresas.length && <option value="">Cargando empresas...</option>}
              {empresas.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.razon_social} · {e.ruc}{e.activo ? "" : " (pausada)"}
                </option>
              ))}
            </select>
          </label>
          <label className={etiqueta}>
            Tipo de cuenta
            <select value={tipoCuenta} onChange={(e) => setTipoCuenta(e.target.value)} className={campo}>
              {TIPOS_CUENTA.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </label>
          <label className={etiqueta}>
            Pagos
            <select value={tipoPago} onChange={(e) => setTipoPago(e.target.value)} className={campo}>
              {TIPOS_PAGO.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-4">
          <div className={etiqueta}>
            Buscar por
            <div className="flex rounded-lg bg-slate-100 p-0.5">
              {[["fechas", "Fecha de pago"], ["periodo", "Periodo tributario"]].map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setModo(id)}
                  className={`rounded-md px-3 py-1 text-xs font-semibold transition-colors ${
                    modo === id ? "bg-white text-ink shadow-sm" : "text-slate-500 hover:text-ink"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {modo === "fechas" ? (
            <>
              <label className={etiqueta}>
                Desde
                <input type="date" value={desde} max={hasta} onChange={(e) => setDesde(e.target.value)} className={campo} />
              </label>
              <label className={etiqueta}>
                Hasta
                <input type="date" value={hasta} min={desde} max={isoLocal(hoy)} onChange={(e) => setHasta(e.target.value)} className={campo} />
              </label>
            </>
          ) : (
            <label className={etiqueta}>
              Periodo tributario
              <input type="month" value={periodo} max={`${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, "0")}`} onChange={(e) => setPeriodo(e.target.value)} className={campo} />
            </label>
          )}
          <button
            type="button"
            onClick={buscarEnSunat}
            disabled={!empresaId || enviando || buscandoEnSunat}
            className="ml-auto flex items-center gap-1.5 rounded-lg bg-accent px-5 py-2 text-sm font-bold text-white transition-all duration-300 ease-out hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
          >
            {enviando || buscandoEnSunat ? <Loader2 size={15} strokeWidth={2} className="animate-spin" /> : <SearchCheck size={15} strokeWidth={2} />}
            {buscandoEnSunat ? "Buscando en SUNAT..." : "Buscar en SUNAT"}
          </button>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          {modo === "fechas"
            ? "SUNAT deja consultar 30 dias por vez; aqui puedes pedir hasta un año y el robot lo parte en tramos."
            : "Por periodo SUNAT tarda mas (unos 20 segundos por tipo de cuenta y de pago)."}
          {" "}La busqueda tarda alrededor de un minuto; puedes seguir usando la aplicacion mientras tanto.
        </p>

        {buscandoEnSunat && (
          <div className="mt-4 flex items-center gap-2 rounded-lg bg-sky-50 px-3 py-2.5 text-sm text-sky-800">
            <Loader2 size={15} strokeWidth={2} className="animate-spin" />
            {ETAPAS[busqueda.etapa] || ETAPAS[busqueda.estado] || "Buscando en SUNAT..."}
          </div>
        )}
      </div>

      {error && <div className="mt-4 rounded-lg border border-red-100 bg-red-50 px-3 py-2.5 text-sm text-red-600">{error}</div>}
      {aviso && <div className="mt-4 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-700">{aviso}</div>}

      <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {[
          { id: "recibidos", titulo: "Recibido en tu cuenta", monto: resumen.recibido, n: resumen.nRecibido, Icon: ArrowDownLeft, color: "text-emerald-600 bg-emerald-50" },
          { id: "pagados", titulo: "Pagado a proveedores", monto: resumen.pagado, n: resumen.nPagado, Icon: ArrowUpRight, color: "text-amber-600 bg-amber-50" },
          { id: "todos", titulo: "Total de depositos", monto: resumen.recibido + resumen.pagado, n: depositos.length, Icon: Search, color: "text-accent bg-accent-light" },
        ].map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setRol(t.id)}
            className={`surface-card flex items-center justify-between p-4 text-left transition-all duration-300 ease-out hover:-translate-y-0.5 ${
              rol === t.id ? "ring-2 ring-accent" : ""
            }`}
          >
            <div>
              <p className="text-xs font-semibold text-slate-500">{t.titulo}</p>
              <p className="mt-1 text-2xl font-extrabold text-ink">{soles.format(t.monto)}</p>
              <p className="text-xs text-slate-500">{t.n} deposito(s)</p>
            </div>
            <span className={`flex h-9 w-9 items-center justify-center rounded-full ${t.color}`}>
              <t.Icon size={17} strokeWidth={2} />
            </span>
          </button>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <span className="text-xs text-slate-500">
          {visibles.length} deposito(s) guardado(s) con estos criterios
          {busqueda?.finalizado_en && !buscandoEnSunat && ` · ultima busqueda en SUNAT: ${new Date(busqueda.finalizado_en).toLocaleString("es-PE")}`}
        </span>
        <div className="relative ml-auto">
          <Search size={14} strokeWidth={1.75} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            placeholder="Buscar cliente, proveedor, comprobante..."
            className="w-72 rounded-lg border border-slate-200 bg-white py-1.5 pl-8 pr-3 text-sm text-ink focus:border-accent focus:outline-none"
          />
        </div>
        <button
          onClick={exportarCsv}
          disabled={!visibles.length}
          className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-4 py-1.5 text-sm font-medium text-slate-700 transition-all duration-300 ease-out hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Download size={15} strokeWidth={1.5} />
          Excel
        </button>
      </div>

      <div className="surface-card mt-3 overflow-x-auto">
        {cargando ? (
          <p className="p-6 text-sm text-slate-500">Cargando...</p>
        ) : !visibles.length ? (
          <p className="p-6 text-sm text-slate-500">
            {depositos.length
              ? "Ningun deposito calza con el filtro."
              : "No hay depositos guardados con estos criterios. Presiona \"Buscar en SUNAT\" para traerlos."}
          </p>
        ) : (
          <table className="w-full min-w-[1100px] border-collapse text-sm">
            <thead>
              <tr className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3">Fecha pago</th>
                <th className="px-3 py-3">Periodo</th>
                <th className="px-3 py-3">Comprobante</th>
                <th className="px-3 py-3">Proveedor</th>
                <th className="px-3 py-3">Adquiriente</th>
                <th className="px-3 py-3">Bien o servicio</th>
                <th className="px-3 py-3 text-right">Monto</th>
                <th className="px-3 py-3">Constancia</th>
                <th className="px-4 py-3">Cuenta</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {visibles.map((d) => {
                const recibido = esRecibido(d);
                return (
                  <tr key={`${d.num_constancia}-${d.tipo_cuenta}`} className="hover:bg-slate-50/60">
                    <td className="whitespace-nowrap px-4 py-2.5">
                      <span
                        className={`mr-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold ${
                          recibido ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"
                        }`}
                        title={recibido ? "Tu cliente lo deposito en tu cuenta" : "Lo depositaste a tu proveedor"}
                      >
                        {recibido ? <ArrowDownLeft size={11} strokeWidth={2.5} /> : <ArrowUpRight size={11} strokeWidth={2.5} />}
                        {recibido ? "Recibido" : "Pagado"}
                      </span>
                      {fechaCorta(d.fecha_pago)}
                    </td>
                    <td className="px-3 py-2.5 text-slate-600">{d.periodo || "—"}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-slate-600">
                      {COMPROBANTE[d.tipo_comprobante] || d.tipo_comprobante} {d.serie}-{d.numero}
                    </td>
                    <td className="max-w-[220px] px-3 py-2.5">
                      <p className="truncate font-medium text-ink" title={d.proveedor}>{d.proveedor}</p>
                      <p className="text-xs text-slate-500">{d.ruc_proveedor}</p>
                    </td>
                    <td className="max-w-[220px] px-3 py-2.5">
                      <p className="truncate font-medium text-ink" title={d.adquiriente}>{d.adquiriente}</p>
                      <p className="text-xs text-slate-500">{d.doc_adquiriente}</p>
                    </td>
                    <td className="max-w-[220px] px-3 py-2.5 text-slate-600">
                      <p className="truncate" title={`${nombreBien(d.tipo_bien)} · ${OPERACION[d.tipo_operacion] || d.tipo_operacion}`}>
                        {nombreBien(d.tipo_bien)}
                      </p>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-right font-bold text-ink">{soles.format(d.monto)}</td>
                    <td className="px-3 py-2.5 text-slate-600">
                      {d.num_constancia}
                      {d.num_pago && <p className="text-xs text-slate-400">NPD {d.num_pago}</p>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-xs text-slate-500">
                      {NOMBRE_CUENTA[d.tipo_cuenta] || d.tipo_cuenta}
                      <p>{d.num_cuenta}</p>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
