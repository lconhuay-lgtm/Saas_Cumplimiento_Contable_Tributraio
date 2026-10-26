"use client";
import { Printer } from "lucide-react";

// Guia para el cliente: generar en el Menu SOL las credenciales de la API
// del SIRE y cargarlas en la plataforma. Pagina sin datos de nadie, pensada
// para imprimir o guardar como PDF desde el navegador (boton de arriba).
const PASOS = [
  {
    titulo: "Entra a SUNAT Operaciones en Línea (SOL)",
    texto: [
      "Usa el RUC, el usuario y la clave SOL de la empresa.",
      "Si ya usas Anzen Sol, el botón \"Ir a SUNAT\" de la empresa te deja dentro de SOL sin escribir nada.",
    ],
  },
  {
    titulo: "Abre la opción de credenciales",
    texto: [
      "En el Menú SOL entra a: Credenciales de API SUNAT › Credenciales de API SUNAT › Gestión Credenciales de API SUNAT.",
      "Aparece la pantalla \"Registre su aplicación\".",
    ],
  },
  {
    titulo: "Registra la aplicación",
    texto: [
      "Nombre de su aplicación: Anzen Sol.",
      "URL de su aplicación: https://anzensol.lckadvisors.com",
      "En la lista de servicios, marca el del SIRE (Registros Electrónicos de Ventas y Compras).",
      "Presiona Guardar.",
    ],
  },
  {
    titulo: "Copia el ID y la clave",
    texto: [
      "SUNAT muestra el ID de la aplicación (client_id) y su clave (client_secret).",
      "Cópialos en un lugar seguro. Si pierdes la clave, genera una nueva aplicación.",
    ],
  },
  {
    titulo: "Pégalos en Anzen Sol",
    texto: [
      "Entra a la empresa › pestaña \"Liquidación en vivo\".",
      "Pega el ID y la clave, presiona \"Guardar credenciales\" y luego \"Probar conexión\".",
      "Si aparece \"Conectado\", la empresa queda lista. Solo el responsable asignado de la empresa puede hacer este paso.",
    ],
  },
];

export default function GuiaApiSirePage() {
  return (
    <main className="mx-auto max-w-3xl bg-white px-6 py-10 text-ink print:py-0">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-accent">Anzen Sol · Liquidación en vivo</p>
          <h1 className="mt-1 text-2xl font-extrabold tracking-tight">Cómo generar las credenciales de la API del SIRE</h1>
          <p className="mt-2 text-sm text-slate-600">
            Con estas credenciales Anzen Sol lee cada madrugada las ventas y compras del mes desde el SIRE de SUNAT, solo
            para consultar. No presenta ni modifica nada en SUNAT. Toma unos 5 minutos por empresa.
          </p>
        </div>
        <button
          onClick={() => window.print()}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-bold text-white print:hidden"
        >
          <Printer size={15} />
          Guardar en PDF
        </button>
      </div>

      <ol className="mt-8 space-y-6">
        {PASOS.map((paso, i) => (
          <li key={paso.titulo} className="flex gap-4 break-inside-avoid">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-sm font-extrabold text-white">
              {i + 1}
            </span>
            <div>
              <h2 className="text-base font-bold">{paso.titulo}</h2>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
                {paso.texto.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </div>
          </li>
        ))}
      </ol>

      <div className="mt-8 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 break-inside-avoid">
        <p className="font-bold">Si SUNAT muestra un error</p>
        <p className="mt-1">
          Si aparece &quot;Ocurrió un error interno&quot; o la lista de servicios sale vacía, es una falla temporal de SUNAT
          (suele pasar de noche). Vuelve a intentarlo más tarde, de preferencia en horario de oficina.
        </p>
      </div>

      <div className="mt-6 rounded-xl border border-slate-200 p-4 text-sm text-slate-600 break-inside-avoid">
        <p className="font-bold text-ink">Seguridad</p>
        <p className="mt-1">
          La clave de la API se guarda cifrada en Anzen Sol y no se vuelve a mostrar. La empresa puede anularla cuando quiera
          desde la misma opción del Menú SOL; en ese caso, la Liquidación en vivo deja de actualizarse hasta que se cargue
          una nueva.
        </p>
      </div>
    </main>
  );
}
