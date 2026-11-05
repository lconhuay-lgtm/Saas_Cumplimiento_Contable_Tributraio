"""
Tabla de detracciones (SPOT) y plazo de deposito para la revision de compras
(Fase 5 de la Liquidacion en vivo, parametros 5.1, 5.2 y 5.4).

Tasas: las del Anexo 1, 2 y 3 de la R.S. 183-2004/SUNAT que entrego el
usuario el 05/11/2026 (con los cambios de 2018: 12 % para intermediacion
laboral, mantenimiento, otros servicios empresariales y demas servicios). Los
codigos son los del Anexo IV, como vienen en la consulta de pagos de SUNAT.
Una tasa None es "por confirmar": el sistema usa el monto depositado y no
calcula lo que falta.

Monto minimo (5.5): S/ 700 por operacion; transporte de bienes S/ 400. El
contador todavia no los confirmo.

Plazo (5.2, confirmado por el contador): hasta el 5.o dia habil del mes
siguiente al de la anotacion de la compra en el Registro de Compras.
"""
from datetime import date, timedelta

MONTO_MINIMO = 700
# Diferencia que se tolera entre lo depositado y lo esperado: la detraccion se deposita en soles enteros.
TOLERANCIA_SOLES = 1
DIA_HABIL_DEL_PLAZO = 5

# codigo: (descripcion, tasa, monto minimo)
TASAS: dict[str, tuple[str, float | None, int]] = {
    "001": ("Azúcar y melaza de caña", 0.10, MONTO_MINIMO),
    "002": ("Código 002 (compras de arroz; tasa por confirmar)", None, MONTO_MINIMO),
    "003": ("Alcohol etílico", 0.10, MONTO_MINIMO),
    "004": ("Recursos hidrobiológicos", 0.04, MONTO_MINIMO),
    "005": ("Maíz amarillo duro", 0.04, MONTO_MINIMO),
    "007": ("Caña de azúcar", 0.10, MONTO_MINIMO),
    "008": ("Madera", 0.04, MONTO_MINIMO),
    "009": ("Arena y piedra", 0.10, MONTO_MINIMO),
    "010": ("Residuos, subproductos, desechos y formas primarias", 0.15, MONTO_MINIMO),
    "011": ("Bienes gravados con el IGV por renuncia a la exoneración", 0.10, MONTO_MINIMO),
    "012": ("Intermediación laboral y tercerización", 0.12, MONTO_MINIMO),
    "013": ("Animales vivos", None, MONTO_MINIMO),
    "014": ("Carnes y despojos comestibles", 0.04, MONTO_MINIMO),
    "015": ("Abonos, cueros y pieles de origen animal", None, MONTO_MINIMO),
    "016": ("Aceite de pescado", 0.10, MONTO_MINIMO),
    "017": ("Harina, polvo y pellets de pescado", 0.04, MONTO_MINIMO),
    "019": ("Arrendamiento de bienes", 0.10, MONTO_MINIMO),
    "020": ("Mantenimiento y reparación de bienes muebles", 0.12, MONTO_MINIMO),
    "021": ("Movimiento de carga", 0.10, MONTO_MINIMO),
    "022": ("Otros servicios empresariales", 0.12, MONTO_MINIMO),
    "023": ("Leche", 0.04, MONTO_MINIMO),
    "024": ("Comisión mercantil", 0.10, MONTO_MINIMO),
    "025": ("Fabricación de bienes por encargo", 0.10, MONTO_MINIMO),
    "026": ("Servicio de transporte de personas", 0.10, MONTO_MINIMO),
    # R.S. 073-2006/SUNAT: no vino en la tabla del usuario; 4 % es lo que dan los depositos reales.
    "027": ("Servicio de transporte de bienes", 0.04, 400),
    "030": ("Contratos de construcción", 0.04, MONTO_MINIMO),
    "031": ("Oro gravado con el IGV", 0.10, MONTO_MINIMO),
    "032": ("Páprika y otros frutos capsicum o pimienta", 0.10, MONTO_MINIMO),
    "034": ("Minerales metálicos no auríferos", 0.10, MONTO_MINIMO),
    "035": ("Bienes exonerados del IGV", 0.015, MONTO_MINIMO),
    "036": ("Oro y demás minerales metálicos exonerados del IGV", 0.015, MONTO_MINIMO),
    "037": ("Demás servicios gravados con el IGV", 0.12, MONTO_MINIMO),
    "039": ("Minerales no metálicos", 0.10, MONTO_MINIMO),
    "040": ("Bien inmueble gravado con el IGV", None, MONTO_MINIMO),
    "041": ("Plomo", 0.15, MONTO_MINIMO),
    "044": ("Servicio de beneficio de minerales metálicos", None, MONTO_MINIMO),
    "045": ("Minerales de oro y sus concentrados", None, MONTO_MINIMO),
    # En la cartera solo aparece en pagos a RUTAS DE LIMA (operacion 09): no es la detraccion de una compra.
    "099": ("Ley 30737 (pagos a RUTAS DE LIMA)", None, MONTO_MINIMO),
}

# Feriados nacionales (5.4). Los sabados y domingos ya no son habiles.
FERIADOS: set[date] = {
    date(2026, 1, 1), date(2026, 4, 2), date(2026, 4, 3), date(2026, 5, 1), date(2026, 6, 7), date(2026, 6, 29),
    date(2026, 7, 23), date(2026, 7, 28), date(2026, 7, 29), date(2026, 8, 6), date(2026, 8, 30), date(2026, 10, 8),
    date(2026, 11, 1), date(2026, 12, 8), date(2026, 12, 9), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 3, 25), date(2027, 3, 26), date(2027, 5, 1), date(2027, 6, 7), date(2027, 6, 29),
    date(2027, 7, 23), date(2027, 7, 28), date(2027, 7, 29), date(2027, 8, 6), date(2027, 8, 30), date(2027, 10, 8),
    date(2027, 11, 1), date(2027, 12, 8), date(2027, 12, 9), date(2027, 12, 25),
}


def descripcion(codigo: str | None) -> str:
    return TASAS[codigo][0] if codigo in TASAS else (f"Código {codigo}" if codigo else "")


def tasa(codigo: str | None) -> float | None:
    return TASAS[codigo][1] if codigo in TASAS else None


def monto_minimo(codigo: str | None) -> int:
    return TASAS[codigo][2] if codigo in TASAS else MONTO_MINIMO


def es_habil(dia: date) -> bool:
    return dia.weekday() < 5 and dia not in FERIADOS


def plazo_deposito(periodo: str) -> date:
    """El 5.o dia habil del mes siguiente al periodo ("AAAA-MM") en que se anoto la compra."""
    anio, mes = int(periodo[:4]), int(periodo[5:7])
    dia = date(anio + (mes == 12), mes % 12 + 1, 1)
    habiles = 0
    while True:
        if es_habil(dia):
            habiles += 1
            if habiles == DIA_HABIL_DEL_PLAZO:
                return dia
        dia += timedelta(days=1)


def habiles_hasta(hoy: date, vence: date) -> int:
    """Dias habiles que faltan de hoy al plazo: 0 si vence hoy, negativo si ya vencio."""
    if vence >= hoy:
        return sum(1 for n in range(1, (vence - hoy).days + 1) if es_habil(hoy + timedelta(days=n)))
    return -sum(1 for n in range(0, (hoy - vence).days) if es_habil(vence + timedelta(days=n)))
