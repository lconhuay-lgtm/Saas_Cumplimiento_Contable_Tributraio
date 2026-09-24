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
