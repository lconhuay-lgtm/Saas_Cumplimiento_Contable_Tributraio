"""Punto de entrada de la API -- Fase 0 + Fase 1."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, empresas, consultas, admin, dashboard, ficha_ruc, cronograma, tareas

app = FastAPI(
    title="Buzon SUNAT multi-RUC -- API",
    description="Auth, tenants, CRUD de empresas, y consultas en vivo al buzon SOL via cola de trabajos.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ajustar a dominios reales antes de produccion
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(empresas.router)
app.include_router(consultas.router)
app.include_router(admin.router)
app.include_router(dashboard.router)
app.include_router(ficha_ruc.router)
app.include_router(cronograma.router)
app.include_router(tareas.router)


@app.on_event("startup")
def _sincronizar_cronograma_al_arrancar():
    # Modulo de cronograma SUNAT: se asegura de que el ejercicio actual (y
    # el siguiente si ya es diciembre) este cargado apenas arranca el
    # backend -- idempotente (no vuelve a descargar si ya esta completo),
    # asi que no le agrega demora real a los arranques normales despues del
    # primero. Si falla (SUNAT caida, sin red, etc.) solo deja un warning en
    # el log -- nunca debe impedir que el backend arranque.
    from app.database import SessionLocal
    from app.cronograma_sunat import asegurar_cronograma_vigente

    db = SessionLocal()
    try:
        resultado = asegurar_cronograma_vigente(db)
        if resultado["anios_sincronizados"]:
            logging.getLogger("app.main").info(f"Cronograma SUNAT sincronizado al arrancar: {resultado}")
    except Exception:
        logging.getLogger("app.main").exception("No se pudo asegurar el cronograma SUNAT al arrancar (no es critico)")
    finally:
        db.close()


@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok"}
