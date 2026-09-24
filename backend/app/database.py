"""Conexion a la base de datos (SQLAlchemy 2.0 style)."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://buzon:buzon_dev_password@localhost:5432/buzon_saas",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependencia de FastAPI: una sesion por request, cerrada al terminar."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
