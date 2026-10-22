"""
Todo lo que depende del dia se calcula con la hora de Peru: el servidor corre
en UTC y desde las 7 p.m. de Peru ya es "manana" alla.
"""
from datetime import date, datetime, timezone

import app.hora_peru as hora_peru
from app.hora_peru import ZONA_PERU
from app.jobs import _parsear_fecha, _vencimiento_tarea_valor
from app.models import TareaObligacion, ValorDeuda

# 21/10/2026 a las 9 p.m. en Peru = 22/10/2026 02:00 UTC.
NOCHE_PERU = datetime(2026, 10, 21, 21, 0, tzinfo=ZONA_PERU)


def test_ayudantes_de_hora_peru(monkeypatch):
    monkeypatch.setattr(hora_peru, "ahora_peru", lambda: NOCHE_PERU)
    assert hora_peru.hoy_peru() == date(2026, 10, 21)
    assert hora_peru.etiqueta_de_hoy() == datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert hora_peru.inicio_de_hoy_peru() == datetime(2026, 10, 21, 5, 0, tzinfo=timezone.utc)


def test_hora_de_publicacion_de_sunat_es_hora_de_peru():
    assert _parsear_fecha("20/10/2026 20:44:00") == datetime(2026, 10, 21, 1, 44, tzinfo=timezone.utc)
    assert _parsear_fecha("01/10/2026 01:15") == datetime(2026, 10, 1, 6, 15, tzinfo=timezone.utc)


def test_vencimiento_de_tareas_de_deuda_es_un_dia():
    hoy = date(2026, 10, 21)
    assert _vencimiento_tarea_valor(ValorDeuda(en_cobranza_coactiva=True), hoy) == datetime(2026, 10, 23, tzinfo=timezone.utc)
    assert _vencimiento_tarea_valor(ValorDeuda(en_cobranza_coactiva=False), hoy) == datetime(2026, 10, 26, tzinfo=timezone.utc)
    notificada = ValorDeuda(en_cobranza_coactiva=False, fecha_notificacion=date(2026, 10, 1))
    assert _vencimiento_tarea_valor(notificada, hoy) == datetime(2026, 10, 22, tzinfo=timezone.utc)  # nunca antes de manana


def test_tarea_que_vence_hoy_no_sale_vencida_a_la_noche(client, db_session, monkeypatch):
    from tests.test_deudas import _crear_empresa, _registrar

    monkeypatch.setattr(hora_peru, "ahora_peru", lambda: NOCHE_PERU)
    headers = _registrar(client)
    empresa_id = _crear_empresa(client, headers, "20111111111")
    for dia in (20, 21):
        db_session.add(TareaObligacion(
            empresa_id=empresa_id, titulo=f"Vence el {dia}", tipo="otro", estado="pendiente",
            fecha_vencimiento=datetime(2026, 10, dia, tzinfo=timezone.utc),
        ))
    db_session.commit()

    vencidas = [t["titulo"] for t in client.get("/tareas?estado=vencida", headers=headers).json()]
    assert vencidas == ["Vence el 20"]
