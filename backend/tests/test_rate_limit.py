"""Rate limiting por RUC (backend/app/rate_limit.py), sobre fakeredis (ver conftest.py)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import ConfiguracionSistema
from app.rate_limit import verificar_limite_ruc, LimiteExcedido
import app.rate_limit as rate_limit


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


def test_verificar_limite_ruc_sin_base_de_datos_cae_al_default():
    """
    conftest.py apunta DATABASE_URL a un host inalcanzable a proposito --
    _configuracion_actual() debe tragarse ese error y devolver None, sin
    tumbar el chequeo de rate limit (Fase 5), usando el default de 60s.
    """
    assert rate_limit.segundos_entre_consultas_ruc() == 60
    verificar_limite_ruc("20555555555")
    with pytest.raises(LimiteExcedido):
        verificar_limite_ruc("20555555555")


def test_verificar_limite_ruc_respeta_la_configuracion_del_panel_maestro(monkeypatch):
    """
    Fase 5: si ConfiguracionSistema.segundos_entre_consultas_mismo_ruc esta
    guardado en la base (panel maestro), el rate limit debe usar ESE valor
    en vez del default de variable de entorno (60s). Se arma una base
    SQLite propia y se monkeypatchea rate_limit.SessionLocal para apuntar
    ahi -- el fixture `client`/`db_session` de conftest.py solo cubre
    get_db() (dependencia de FastAPI), no las sesiones que este modulo abre
    por su cuenta.
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    session = TestingSessionLocal()
    session.add(ConfiguracionSistema(id="global", segundos_entre_consultas_mismo_ruc=5))
    session.commit()
    session.close()

    monkeypatch.setattr(rate_limit, "SessionLocal", TestingSessionLocal)

    assert rate_limit.segundos_entre_consultas_ruc() == 5

    verificar_limite_ruc("20777777777")
    with pytest.raises(LimiteExcedido):
        verificar_limite_ruc("20777777777")
    ttl = rate_limit.redis_conn.ttl("sunat:ultima_consulta:20777777777")
    assert 0 < ttl <= 5  # el TTL que Redis guardo viene de la config (5s), no del default de 60s

    engine.dispose()
