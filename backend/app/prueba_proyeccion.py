"""
Prueba hacia atras de la proyeccion al cierre (Fase 6): para cada empresa
activada y cada mes cerrado con la propuesta del SIRE leida, rehace lo que se
sabia el dia 5, 8, 10, 15, 20 y 25 (con la fecha de emision de cada
comprobante), proyecta con cada forma de pesar el mes (PESOS_DEL_MES) y lo
compara con el cierre: el estimado del mes completo o, si ya se presento, el
0621. Solo lee la base.

Aceptacion (plan, Fase 6): el dia 20 la proyeccion del IGV queda a menos del
10 % del cierre en la mayoria de las empresas.

Uso, en el servidor:
    docker compose -f docker-compose.yml exec -T backend python -m app.prueba_proyeccion 2026-10 [2026-09 ...]
"""
import statistics
import sys
from datetime import timedelta

from app.calculo_liquidacion import (
    PESOS_DEL_MES, _Datos, _DatosAl, _calcular, _igv_declarado, _limites_del_mes, proyectar,
)
from app.database import SessionLocal
from app.models import Empresa, LiquidacionEmpresa

DIAS = (5, 8, 10, 15, 20, 25)
# Se mide solo donde hay ventas que proyectar.
VENTAS_MINIMAS = 1000
# Acierto: a menos del 10 % del cierre; con cierres chicos, a menos de S/ 100.
TOLERANCIA = 0.10
TOLERANCIA_MINIMA = 100


def acierta(proyectado: int, cierre: int) -> bool:
    return abs(proyectado - cierre) <= max(TOLERANCIA * cierre, TOLERANCIA_MINIMA)


def probar(db, periodos: list[str]) -> tuple[int, dict]:
    """Devuelve cuantos casos se midieron y, por (peso, dia), los aciertos y los errores de ventas."""
    filas = (
        db.query(Empresa, LiquidacionEmpresa)
        .join(LiquidacionEmpresa, LiquidacionEmpresa.empresa_id == Empresa.id)
        .filter(LiquidacionEmpresa.activa.is_(True), Empresa.activo.is_(True))
        .all()
    )
    resultados = {(p, d): {"aciertos": [], "error_ventas": []} for p in PESOS_DEL_MES for d in DIAS}
    casos, vistos = 0, set()
    for empresa, config in filas:
        if empresa.ruc in vistos:  # la misma empresa activada en dos estudios
            continue
        vistos.add(empresa.ruc)
        datos = _Datos(db, empresa.id)
        for periodo in periodos:
            if datos.ultima_lectura("sire", periodo) is None:
                continue
            cierre = _calcular(datos, periodo, config.regimen)["casillas"]
            if cierre["131"] < VENTAS_MINIMAS:
                continue
            declarado = _igv_declarado(datos, periodo)
            igv_cierre = declarado if declarado is not None else max(cierre["681"] - cierre["185"], 0)
            casos += 1
            inicio, _ = _limites_del_mes(periodo)
            for dia in DIAS:
                al_dia = _DatosAl(datos, periodo, inicio + timedelta(days=dia - 1))
                casillas = _calcular(al_dia, periodo, config.regimen)["casillas"]
                for peso in PESOS_DEL_MES:
                    p = proyectar(al_dia, periodo, config.regimen, inicio + timedelta(days=dia - 1), casillas, peso)
                    resultados[(peso, dia)]["aciertos"].append(acierta(p["igv"], igv_cierre))
                    resultados[(peso, dia)]["error_ventas"].append(abs(p["ventas"] - cierre["131"]) / cierre["131"])
    return casos, resultados


def main(periodos: list[str]) -> None:
    db = SessionLocal()
    try:
        casos, resultados = probar(db, periodos)
    finally:
        db.close()
    print(f"Meses {', '.join(periodos)}: {casos} empresa-mes con ventas de S/ {VENTAS_MINIMAS:,} o mas")
    print(f"{'peso del mes':14} {'dia':>4} | {'IGV a menos del 10 %':>21} | {'error de ventas (mediana)':>26}")
    for (peso, dia), r in resultados.items():
        if r["aciertos"]:
            print(f"{peso:14} {dia:>4} | {100 * sum(r['aciertos']) / len(r['aciertos']):>20.0f}% | "
                  f"{100 * statistics.median(r['error_ventas']):>25.1f}%")


if __name__ == "__main__":
    main(sys.argv[1:] or ["2026-10"])
