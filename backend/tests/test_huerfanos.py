"""Limpieza de jobs huerfanos (app/huerfanos.py): un job cortado a mitad no queda en_progreso para siempre."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

import app.huerfanos as huerfanos
from app.models import ConsultaDetraccionesJob, ConsultaJob, LiquidacionLectura
from tests.test_rbac_miembro import _armar_tenant_con_miembro


def test_jobs_huerfanos_con_limite_por_tipo(client, db_session, monkeypatch):
    monkeypatch.setattr(huerfanos, "SessionLocal", sessionmaker(bind=db_session.get_bind(), autoflush=False))
    emp = _armar_tenant_con_miembro(client, db_session)["empresa_asignada_id"]
    ahora = datetime.now(timezone.utc)

    def hace(minutos):
        return ahora - timedelta(minutes=minutos)

    def lectura(minutos):
        return LiquidacionLectura(empresa_id=emp, fuente="sire", periodo_desde="2026-10", periodo_hasta="2026-10",
                                  estado="en_progreso", iniciado_en=hace(minutos))

    filas = {
        "buzon_cortado": ConsultaJob(empresa_id=emp, estado="en_progreso", iniciado_en=hace(20)),
        # Una carga inicial de detracciones puede durar hasta 40 minutos.
        "detraccion_en_curso": ConsultaDetraccionesJob(empresa_id=emp, estado="en_progreso", etapa="leyendo", iniciado_en=hace(30)),
        "detraccion_cortada": ConsultaDetraccionesJob(
            empresa_id=emp, estado="en_progreso", etapa="abriendo_detracciones", iniciado_en=hace(50)),
        # El trabajo de lecturas de la Liquidacion en vivo tiene 90 minutos.
        "lectura_en_curso": lectura(60),
        "lectura_cortada": lectura(100),
        "pendiente": ConsultaDetraccionesJob(empresa_id=emp, estado="pendiente"),
    }
    db_session.add_all(filas.values())
    db_session.commit()

    assert huerfanos.marcar_jobs_huerfanos() == 3
    db_session.expire_all()
    assert {k: (f.estado, f.etapa) for k, f in filas.items()} == {
        "buzon_cortado": ("error", None),
        "detraccion_en_curso": ("en_progreso", "leyendo"),
        "detraccion_cortada": ("error", None),
        "lectura_en_curso": ("en_progreso", None),
        "lectura_cortada": ("error", None),
        "pendiente": ("pendiente", None),
    }
    assert filas["detraccion_cortada"].error == huerfanos.MENSAJE_HUERFANO
    assert huerfanos.marcar_jobs_huerfanos() == 0
