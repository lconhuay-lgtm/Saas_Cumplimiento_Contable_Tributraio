"""Clasifica cada mensaje del buzon por tipo de documento a partir del texto del asunto."""
import re

_PATRONES_TIPO = [
    ("Orden de Pago", ["orden de pago"]),
    ("Resolución Coactiva", ["ejecucion coactiva", "resolucion coactiva", "cobranza coactiva"]),
    ("Resolución de Multa", ["resolucion de multa"]),
    ("Resolución de Determinación", ["resolucion de determinacion"]),
    ("Resolución de Intendencia", ["resolucion de intendencia"]),
    ("Resolución de Reclamación", ["resolucion de reclamacion"]),
    ("Esquela", ["esquela"]),
    ("Requerimiento", ["requerimiento"]),
    ("Carta Inductiva", ["carta inductiva"]),
    ("Comunicación", ["comunicacion"]),
]
TIPO_OTROS = "Otros"


def _sin_tildes(texto: str) -> str:
    reemplazos = str.maketrans("áéíóúñ", "aeioun")
    return texto.translate(reemplazos)


def clasificar_tipo(asunto: str) -> str:
    texto = _sin_tildes((asunto or "").lower())
    texto = re.sub(r"\s+", " ", texto)
    for etiqueta, palabras_clave in _PATRONES_TIPO:
        if any(p in texto for p in palabras_clave):
            return etiqueta
    return TIPO_OTROS


def tipos_disponibles() -> list[str]:
    return [etiqueta for etiqueta, _ in _PATRONES_TIPO] + [TIPO_OTROS]


# Mismo orden que _PATRONES_TIPO (y que la paleta de colores en
# frontend/lib/tiposMensaje.js, que va de mas a menos severo) -- se
# reexpone como un dict de orden para no recorrer la lista entera cada vez
# que hay que comparar dos tipos.
_ORDEN_SEVERIDAD = {etiqueta: i for i, etiqueta in enumerate(tipos_disponibles())}


def tipo_mas_severo(tipos) -> str | None:
    """
    Dado un iterable de `tipo` (los valores que devuelve clasificar_tipo,
    ej. de varios mensajes sin leer de una misma empresa), devuelve el mas
    severo de todos -- "Orden de Pago" le gana a "Esquela", que le gana a
    "Otros", etc. None si la lista viene vacia. Pensado para que un
    resumen (ej. el conteo de "pendientes" en la lista de empresas) pueda
    mostrar la severidad del PEOR caso sin tener que listar cada tipo por
    separado -- mismo patron que SAP/Oracle usan en sus badges de resumen
    ("worst-of" status).
    """
    mas_severo = None
    for tipo in tipos:
        if mas_severo is None or _ORDEN_SEVERIDAD.get(tipo, len(_ORDEN_SEVERIDAD)) < _ORDEN_SEVERIDAD.get(
            mas_severo, len(_ORDEN_SEVERIDAD)
        ):
            mas_severo = tipo
    return mas_severo
