"""Conexion a Redis y cola RQ, compartida entre el backend (encola) y el worker (consume)."""
import os
from redis import Redis
from rq import Queue

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
redis_conn = Redis.from_url(REDIS_URL)
cola_consultas = Queue("consultas_buzon", connection=redis_conn)
