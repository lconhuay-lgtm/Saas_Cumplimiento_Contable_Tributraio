import { api, API_URL } from "./api";

// "Ingreso directo" a SUNAT ya logueado, el mismo de las tarjetas de
// /empresas (ver entrarDirectoASunat en app/empresas/page.js), para usarlo
// desde otras pantallas como el buzon de una empresa.
const DESTINOS = {
  sunat: { obtenerToken: api.obtenerTokenIngresoDirecto, ruta: "ingreso-directo" },
  declaraciones: { obtenerToken: api.obtenerTokenIngresoDirectoDeclaraciones, ruta: "ingreso-directo-declaraciones" },
};

// Hay que llamarla directo en el clic (sin un await antes): la pestana se abre
// vacia en ese mismo instante -- si no, el navegador la bloquea como popup --
// y se la manda a SUNAT cuando llega el token.
export async function abrirIngresoDirecto(empresaId, destino) {
  const { obtenerToken, ruta } = DESTINOS[destino];
  const pestana = window.open("", "_blank");
  try {
    const { token } = await obtenerToken(empresaId);
    if (pestana) pestana.location.href = `${API_URL}/empresas/${empresaId}/${ruta}?token=${encodeURIComponent(token)}`;
  } catch (err) {
    if (pestana) pestana.close();
    throw err;
  }
}
