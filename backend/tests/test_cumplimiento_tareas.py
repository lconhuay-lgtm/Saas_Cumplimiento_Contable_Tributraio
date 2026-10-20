"""
Enlace de Cumplimiento con Tareas: tareas que se completan solas cuando SUNAT
ya registra lo presentado, deteccion de la obligacion PLAME, embargos y los
avisos (tarea + correo) por deudas/embargos nuevos.
"""
from datetime import date, datetime, timedelta, timezone

from adapter import normalizar_embargo, normalizar_valor
from app.jobs import (
    aplicar_lectura_embargos, aplicar_lectura_valores, avisar_novedades_deuda, completar_tareas_por_referencia,
)
from app.models import DeclaracionSunat, EmpresaObligacion, SireEstadoPeriodo, TareaObligacion
from app.tareas import NOMBRE_PLAME_DETECTADA, revisar_obligacion_plame, sincronizar_tareas_con_sunat
from tests.test_deudas import _crudo, _empresa, _tenant


_REGLA_POR_TIPO = {"sire": "cronograma_sire"}


def _tarea(db, empresa, tipo, periodo, regla=None):
    ob = EmpresaObligacion(
        empresa_id=empresa.id, tipo=tipo, nombre=f"{tipo} {periodo} {regla or ''}".strip(),
        regla_vencimiento=regla or _REGLA_POR_TIPO.get(tipo, "cronograma_sunat"), activa=True,
        dia_fijo=30 if regla == "dia_fijo_mes" else None,
    )
    db.add(ob)
    db.flush()
    t = TareaObligacion(
        empresa_id=empresa.id, empresa_obligacion_id=ob.id, titulo=f"{tipo} {periodo}", tipo=tipo,
        periodo=periodo, estado="pendiente",
    )
    db.add(t)
    db.commit()
    return t


def test_tareas_se_completan_solas_al_verificar_en_sunat(db_session):
    empresa = _empresa(db_session, _tenant(db_session))
    igv_ago = _tarea(db_session, empresa, "igv_renta", "2026-08")
    plame_ago = _tarea(db_session, empresa, "planilla", "2026-08")
    sire_ago = _tarea(db_session, empresa, "sire", "2026-08")
    igv_set = _tarea(db_session, empresa, "igv_renta", "2026-09")
    sire_set = _tarea(db_session, empresa, "sire", "2026-09")
    afp_ago = _tarea(db_session, empresa, "afp", "2026-08")
    # "Planilla mensual" con dia fijo = pago de sueldos, no la PLAME.
    sueldos_ago = _tarea(db_session, empresa, "planilla", "2026-08", regla="dia_fijo_mes")
    db_session.add_all([
        DeclaracionSunat(empresa_id=empresa.id, periodo="2026-08", formulario="0621", num_orden="1207052856",
                         fecha_presentacion=date(2026, 9, 17)),
        DeclaracionSunat(empresa_id=empresa.id, periodo="2026-08", formulario="0601", num_orden="1207016106",
                         fecha_presentacion=date(2026, 9, 17)),
        SireEstadoPeriodo(empresa_id=empresa.id, libro="RVIE", periodo="2026-08", cod_estado="02", des_estado="Presentado", presentado=True),
        SireEstadoPeriodo(empresa_id=empresa.id, libro="RCE", periodo="2026-08", cod_estado="02", des_estado="Presentado", presentado=True),
        # Septiembre: solo el RVIE presentado -> la tarea SIRE sigue pendiente.
        SireEstadoPeriodo(empresa_id=empresa.id, libro="RVIE", periodo="2026-09", cod_estado="02", des_estado="Presentado", presentado=True),
        SireEstadoPeriodo(empresa_id=empresa.id, libro="RCE", periodo="2026-09", cod_estado="03", des_estado="No Presentado", presentado=False),
    ])
    db_session.commit()

    assert sincronizar_tareas_con_sunat(db_session, empresa.id) == 3
    db_session.commit()
    for t in (igv_ago, plame_ago, sire_ago):
        db_session.refresh(t)
        assert t.estado == "completado" and t.verificado_sunat_en is not None
    assert "0621" in igv_ago.observaciones and "17/09/2026" in igv_ago.observaciones
    assert igv_ago.fecha_completado.date() == date(2026, 9, 17)
    for t in (igv_set, sire_set, afp_ago, sueldos_ago):
        db_session.refresh(t)
        assert t.estado == "pendiente"

    # Si alguien la reabre a mano, no se vuelve a completar sola.
    igv_ago.estado = "pendiente"
    db_session.commit()
    assert sincronizar_tareas_con_sunat(db_session, empresa.id) == 0


def test_obligacion_plame_se_detecta_desde_sunat(db_session):
    tenant = _tenant(db_session)
    con_plame = _empresa(db_session, tenant, ruc="20100000011")
    apagada = _empresa(db_session, tenant, ruc="20100000012")
    solo_sueldos = _empresa(db_session, tenant, ruc="20100000013")
    hace_un_mes = (datetime.now(timezone.utc) - timedelta(days=35)).strftime("%Y-%m")
    for e in (con_plame, apagada, solo_sueldos):
        db_session.add(DeclaracionSunat(empresa_id=e.id, periodo=hace_un_mes, formulario="0601", num_orden=f"9{e.ruc}"))
    # El usuario la desactivo a mano: se respeta.
    db_session.add(EmpresaObligacion(empresa_id=apagada.id, tipo="planilla", nombre="PLAME", regla_vencimiento="cronograma_sunat", activa=False))
    # Solo tiene el pago de sueldos (dia fijo): eso no es la PLAME.
    db_session.add(EmpresaObligacion(empresa_id=solo_sueldos.id, tipo="planilla", nombre="Planilla mensual", regla_vencimiento="dia_fijo_mes", dia_fijo=30, activa=True))
    db_session.commit()

    assert revisar_obligacion_plame(db_session, con_plame.id) == "creada"
    db_session.commit()
    ob = db_session.query(EmpresaObligacion).filter(EmpresaObligacion.empresa_id == con_plame.id).one()
    assert (ob.tipo, ob.nombre, ob.regla_vencimiento, ob.activa) == ("planilla", NOMBRE_PLAME_DETECTADA, "cronograma_sunat", True)
    assert revisar_obligacion_plame(db_session, con_plame.id) is None
    assert revisar_obligacion_plame(db_session, apagada.id) is None
    assert revisar_obligacion_plame(db_session, solo_sueldos.id) == "creada"


def _embargo(rc, estado="Notificado al Contribuyente", monto="4078.00"):
    return normalizar_embargo({
        "rcEmbargo": f"{rc}    ", "numRucTer": "20100054184", "nomTercero": "CLINICA INTERNACIONAL S A      ",
        "fecRegistro": "09/11/2022", "fecNotif": "", "estado": estado, "monEmbargado": monto, "monEntregado": 0.0,
        "monPendiente": monto, "rcLevantamiento": "0", "fecLev": "", "desImposibilidad": " ",
    })


def test_embargos_avisos_y_tareas_automaticas(db_session):
    empresa = _empresa(db_session, _tenant(db_session))
    ahora = datetime.now(timezone.utc)
    base = aplicar_lectura_embargos(db_session, empresa.id, [_embargo("E1"), _embargo("E2", estado="Levantado")], ahora, avisar_nuevos=False)
    assert base == {"nuevos_activos": [], "levantados": []}
    db_session.commit()

    # Siguiente lectura: E1 se levanta y aparece E3 activo.
    novedades = aplicar_lectura_embargos(
        db_session, empresa.id,
        [_embargo("E1", estado="Levantado"), _embargo("E2", estado="Levantado"), _embargo("E3", monto="1500.50")],
        ahora + timedelta(days=1),
    )
    assert [e.rc_embargo for e in novedades["nuevos_activos"]] == ["E3"]
    assert novedades["levantados"] == ["E1"]
    db_session.commit()

    aplicar_lectura_valores(db_session, empresa.id, [normalizar_valor(_crudo("V1"))], ahora, avisar_nuevos=False)
    cuenta = aplicar_lectura_valores(
        db_session, empresa.id, [normalizar_valor(_crudo("V1")), normalizar_valor(_crudo("V2"))], ahora + timedelta(days=1)
    )
    avisar_novedades_deuda(db_session, empresa, cuenta["para_avisar"], novedades["nuevos_activos"])
    db_session.commit()
    tareas = {t.referencia_sunat: t for t in db_session.query(TareaObligacion).filter(TareaObligacion.tipo == "deuda")}
    assert set(tareas) == {"valor:V2", "embargo:E3"}
    assert tareas["valor:V2"].prioridad == "urgente"  # esta en cobranza coactiva
    assert "V2" in tareas["valor:V2"].titulo and "S/ 899.00" in tareas["valor:V2"].titulo
    assert tareas["embargo:E3"].prioridad == "urgente"

    # El valor se paga y el embargo se levanta -> las tareas se completan solas.
    cuenta = aplicar_lectura_valores(db_session, empresa.id, [normalizar_valor(_crudo("V1"))], ahora + timedelta(days=2))
    assert cuenta["desaparecidos"] == ["V2"]
    assert completar_tareas_por_referencia(db_session, empresa.id, ["valor:V2", "embargo:E3"], "prueba") == 2
    db_session.commit()
    assert all(t.estado == "completado" and t.verificado_sunat_en for t in db_session.query(TareaObligacion))
