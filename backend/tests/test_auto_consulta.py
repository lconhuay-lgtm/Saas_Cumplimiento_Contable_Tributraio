"""
Al crear una empresa (individual), debe encolarse una consulta automatica
-- a pedido, para que el usuario tenga mensajes reales desde el primer
momento en vez de ver la empresa vacia hasta acordarse de apretar
"Consultar" a mano.
"""
from app.models import ConsultaJob


def test_crear_empresa_encola_consulta_automatica(client, db_session):
    resp = client.post(
        "/auth/registro",
        json={"nombre_tenant": "Estudio Auto", "email": "auto@example.com", "password": "ClaveSegura123!"},
    )
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    empresa_id = client.post(
        "/empresas",
        json={"ruc": "20111111111", "razon_social": "Empresa Nueva", "usuario_sol": "x", "clave_sol": "x"},
        headers=headers,
    ).json()["id"]

    jobs = db_session.query(ConsultaJob).filter(ConsultaJob.empresa_id == empresa_id).all()
    assert len(jobs) == 1, "crear una empresa deberia encolar exactamente una consulta automatica"
    assert jobs[0].estado == "pendiente"
