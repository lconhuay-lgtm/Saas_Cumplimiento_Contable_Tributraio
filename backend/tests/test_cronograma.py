"""
_empresas_para_cronograma (backend/app/cronograma_sunat.py): que empresas
corresponde considerar para el cronograma de vencimientos y para el modulo
de Tareas (que reusa el mismo filtro).
"""
from app.models import Tenant, Empresa
from app.cronograma_sunat import empresas_para_cronograma


def _crear_empresa(db_session, tenant_id, ruc, estado_contribuyente=None, activo=True):
    empresa = Empresa(
        tenant_id=tenant_id,
        ruc=ruc,
        razon_social=f"Empresa {ruc}",
        activo=activo,
        estado_contribuyente=estado_contribuyente,
    )
    db_session.add(empresa)
    db_session.commit()
    return empresa


def test_empresa_activa_sin_estado_leido_aun_aparece(db_session):
    tenant = Tenant(nombre="Estudio Test")
    db_session.add(tenant)
    db_session.commit()

    _crear_empresa(db_session, tenant.id, "20111111111", estado_contribuyente=None)

    rucs = {e.ruc for e in empresas_para_cronograma(db_session, tenant.id)}
    assert rucs == {"20111111111"}


def test_empresa_activo_normal_aparece(db_session):
    tenant = Tenant(nombre="Estudio Test")
    db_session.add(tenant)
    db_session.commit()

    _crear_empresa(db_session, tenant.id, "20222222222", estado_contribuyente="ACTIVO")

    rucs = {e.ruc for e in empresas_para_cronograma(db_session, tenant.id)}
    assert rucs == {"20222222222"}


def test_empresa_de_baja_no_aparece(db_session):
    tenant = Tenant(nombre="Estudio Test")
    db_session.add(tenant)
    db_session.commit()

    _crear_empresa(db_session, tenant.id, "20333333333", estado_contribuyente="BAJA DE OFICIO")

    assert empresas_para_cronograma(db_session, tenant.id) == []


def test_empresa_en_suspension_temporal_no_aparece(db_session):
    """
    Regresion del hueco encontrado en el analisis: el filtro original solo
    reconocia "%BAJA%", no "%SUSPENSION%" -- una empresa en Suspension
    Temporal seguia apareciendo en el cronograma como si tuviera
    obligaciones corrientes.
    """
    tenant = Tenant(nombre="Estudio Test")
    db_session.add(tenant)
    db_session.commit()

    _crear_empresa(db_session, tenant.id, "20444444444", estado_contribuyente="SUSPENSION TEMPORAL")

    assert empresas_para_cronograma(db_session, tenant.id) == []


def test_empresa_inactiva_no_aparece_aunque_este_activa_en_sunat(db_session):
    tenant = Tenant(nombre="Estudio Test")
    db_session.add(tenant)
    db_session.commit()

    _crear_empresa(db_session, tenant.id, "20555555555", estado_contribuyente="ACTIVO", activo=False)

    assert empresas_para_cronograma(db_session, tenant.id) == []
