"""
Fixtures compartidas de la suite (Fase R6 del plan de remediacion).

Dos cosas hay que resolver ANTES de importar cualquier modulo de la app:

1. Redis real -> fakeredis. El parche va sobre redis.Redis.from_url, no
   sobre app.queue_conn.redis_conn directamente -- varios modulos (
   rate_limit.py, scheduler_job.py) hacen "from app.queue_conn import
   redis_conn", lo que crea su PROPIA referencia al objeto en el momento
   del import. Si el parche llegara despues de esos imports, cada modulo
   seguiria apuntando al Redis real de todos modos. Parchando from_url()
   antes de que app.queue_conn se importe por primera vez, TODOS terminan
   compartiendo la misma instancia fake.
2. DATABASE_URL apunta a un puerto invalido (falla rapido con "connection
   refused", no con un timeout de red) -- app.database crea su engine real
   contra esto al importarse, y el evento de arranque de FastAPI
   (_sincronizar_cronograma_al_arrancar) lo usa directo. Eso ya esta
   protegido con un try/except en main.py (nunca tumba el arranque), pero
   sin este DATABASE_URL valido-pero-inalcanzable podria intentar conectar
   a un host que no responde y demorar la suite entera.
"""
import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-solo-para-pruebas")
os.environ.setdefault("ENTORNO", "dev")
os.environ.setdefault("CREDENCIALES_FERNET_KEY", "")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")
os.environ.setdefault("DATABASE_URL", "postgresql://invalido:invalido@localhost:1/invalido")

import fakeredis
import redis

_fake_redis = fakeredis.FakeStrictRedis()
redis.Redis.from_url = lambda *args, **kwargs: _fake_redis

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
import app.models  # noqa: F401 -- registra todas las tablas en Base.metadata
from app.main import app


@pytest.fixture()
def db_session():
    """
    SQLite en memoria, tablas recreadas de cero en cada test. StaticPool es
    obligatorio aca: sin el, cada conexion que pide el pool de SQLAlchemy
    abriria un ":memory:" DISTINTO e independiente, y las tablas creadas en
    una no existirian para otra.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    """TestClient con la sesion SQLite de arriba en vez de Postgres real."""

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _limpiar_fakeredis():
    """Evita que el estado de un test (rate limit, banderas de alerta) se filtre al siguiente."""
    yield
    _fake_redis.flushall()
