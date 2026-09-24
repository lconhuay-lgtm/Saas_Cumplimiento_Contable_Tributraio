"""
Almacenamiento de los documentos PDF descargados del buzon SUNAT.

Dos modos, elegidos por ALMACENAMIENTO_MODO:

- "local" (default): guarda el archivo dentro de /data/sunat/documentos/...
  -- la misma carpeta que ya esta montada al host en desarrollo (ver
  docker-compose.yml). Cero configuracion extra, pensado para desarrollo y
  para el volumen real que maneja este producto (unos pocos GB al año,
  calculado en base al numero de empresas y notificaciones tipico).

- "s3": sube el archivo a un bucket compatible con la API de S3. Pensado
  para Cloudflare R2 en produccion (sin costo de egreso, 10GB gratis al
  mes), pero funciona igual con AWS S3, Backblaze B2, o un MinIO local --
  todos hablan el mismo protocolo. Se activa con ALMACENAMIENTO_MODO=s3 y
  las variables S3_*.

La referencia que se guarda en MensajeBuzon.documento_ref es agnostica al
modo: un string opaco que solo este modulo sabe interpretar (ruta relativa
en modo local, "key" del objeto en modo s3). Nada fuera de este archivo
necesita saber cual de los dos modos esta activo.
"""
import os
import logging

logger = logging.getLogger("app.almacenamiento")

MODO = os.environ.get("ALMACENAMIENTO_MODO", "local").lower()

# ---- Modo local ----
LOCAL_BASE_DIR = os.environ.get("SUNAT_BASE_DIR", "/data/sunat")
DOCUMENTOS_SUBDIR = "documentos"

# ---- Modo S3 (Cloudflare R2 / AWS S3 / Backblaze B2 / MinIO) ----
S3_BUCKET = os.environ.get("S3_BUCKET", "")
# Vacio = AWS S3 real. Con valor (p.ej. https://<cuenta>.r2.cloudflarestorage.com)
# = cualquier otro proveedor compatible con S3, como R2.
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "") or None
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
S3_REGION = os.environ.get("S3_REGION", "auto")

_cliente_s3 = None


class AlmacenamientoError(Exception):
    """Fallo guardando o leyendo un documento -- el llamador decide si es fatal o solo se loguea."""


def _cliente():
    global _cliente_s3
    if _cliente_s3 is None:
        import boto3  # import diferido: solo hace falta si de verdad se usa modo s3

        _cliente_s3 = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT_URL,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name=S3_REGION,
        )
    return _cliente_s3


def _clave_objeto(empresa_id: str, mensaje_id: str) -> str:
    return f"{empresa_id}/{mensaje_id}.pdf"


def guardar_documento(ruta_local_origen: str, empresa_id: str, mensaje_id: str) -> str:
    """
    Copia (modo local) o sube (modo s3) el PDF que el scraper ya descargo
    en ruta_local_origen (dentro del contenedor del worker) al
    almacenamiento definitivo. Devuelve la referencia a guardar en
    MensajeBuzon.documento_ref.

    No borra ruta_local_origen -- esa carpeta de descargas ya tiene su
    propia limpieza automatica por antiguedad (ver core_scraper/data_access.py),
    asi que no hace falta duplicar esa logica aca.
    """
    try:
        if MODO == "s3":
            clave = _clave_objeto(empresa_id, mensaje_id)
            _cliente().upload_file(ruta_local_origen, S3_BUCKET, clave)
            logger.info(f"Documento subido a S3: s3://{S3_BUCKET}/{clave}")
            return clave
        else:
            destino_dir = os.path.join(LOCAL_BASE_DIR, DOCUMENTOS_SUBDIR, empresa_id)
            os.makedirs(destino_dir, exist_ok=True)
            ruta_destino = os.path.join(destino_dir, f"{mensaje_id}.pdf")
            with open(ruta_local_origen, "rb") as origen, open(ruta_destino, "wb") as salida:
                salida.write(origen.read())
            logger.info(f"Documento guardado localmente: {ruta_destino}")
            return f"{DOCUMENTOS_SUBDIR}/{empresa_id}/{mensaje_id}.pdf"
    except Exception as e:
        raise AlmacenamientoError(f"No se pudo guardar el documento: {e}") from e


def guardar_documento_bytes(contenido: bytes, empresa_id: str, mensaje_id: str) -> str:
    """
    Igual que guardar_documento(), pero para cuando el PDF ya esta en
    memoria (bytes) en vez de en un archivo en disco -- por ejemplo el PDF
    de la Ficha RUC, generado directamente via Chrome DevTools (Page.
    printToPDF) sin pasar por la carpeta de descargas del scraper.
    """
    try:
        if MODO == "s3":
            clave = _clave_objeto(empresa_id, mensaje_id)
            _cliente().put_object(Bucket=S3_BUCKET, Key=clave, Body=contenido)
            logger.info(f"Documento subido a S3: s3://{S3_BUCKET}/{clave}")
            return clave
        else:
            destino_dir = os.path.join(LOCAL_BASE_DIR, DOCUMENTOS_SUBDIR, empresa_id)
            os.makedirs(destino_dir, exist_ok=True)
            ruta_destino = os.path.join(destino_dir, f"{mensaje_id}.pdf")
            with open(ruta_destino, "wb") as salida:
                salida.write(contenido)
            logger.info(f"Documento guardado localmente: {ruta_destino}")
            return f"{DOCUMENTOS_SUBDIR}/{empresa_id}/{mensaje_id}.pdf"
    except Exception as e:
        raise AlmacenamientoError(f"No se pudo guardar el documento: {e}") from e


def leer_documento(referencia: str) -> bytes:
    """Devuelve los bytes del PDF para servirlo por la API. Lanza AlmacenamientoError si no existe o falla la lectura."""
    try:
        if MODO == "s3":
            objeto = _cliente().get_object(Bucket=S3_BUCKET, Key=referencia)
            return objeto["Body"].read()
        else:
            ruta = os.path.join(LOCAL_BASE_DIR, referencia)
            with open(ruta, "rb") as f:
                return f.read()
    except FileNotFoundError as e:
        raise AlmacenamientoError(f"El documento ya no esta disponible: {e}") from e
    except Exception as e:
        raise AlmacenamientoError(f"No se pudo leer el documento: {e}") from e
