"""Rate limiting por RUC (backend/app/rate_limit.py), sobre fakeredis (ver conftest.py)."""
import pytest

from app.rate_limit import verificar_limite_ruc, LimiteExcedido


def test_verificar_limite_ruc_bloquea_repeticion_inmediata():
    verificar_limite_ruc("20111111111")
    with pytest.raises(LimiteExcedido):
        verificar_limite_ruc("20111111111")


def test_verificar_limite_ruc_no_bloquea_ruc_distinto():
    """
    Regresion de un reporte real: 'parecia' bloquear entre empresas
    distintas. La clave de Redis incluye el RUC -- consultar un RUC no debe
    afectar a otro.
    """
    verificar_limite_ruc("20111111111")
    verificar_limite_ruc("20999999999")  # no debe lanzar
