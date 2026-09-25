"""
Seguridad: hash de contrasenas de usuarios, JWT, y cifrado de credenciales SOL.

Cifrado de credenciales -- patron de envelope encryption (Fase 1, semana 5):
  1. Cada credencial SOL tiene su propia DEK (Data Encryption Key) generada
     al azar, y la clave SOL se cifra con esa DEK.
  2. La DEK se cifra ("se envuelve") con una clave maestra -- eso es lo que
     se guarda como dek_cifrada. La clave maestra nunca cifra la clave SOL
     directamente.
  3. Para descifrar: primero se desenvuelve la DEK con la clave maestra, y
     recien con esa DEK se descifra la clave SOL.

Por que importa: si una fila de la tabla se filtra sola, no alcanza -- hace
falta ademas la clave maestra. Y si la clave maestra se compromete, cada
credencial sigue teniendo su propia DEK (no es "una clave abre todo").

Esta version usa Fernet local como clave maestra (CREDENCIALES_FERNET_KEY)
para poder correrlo sin depender de una cuenta cloud. El reemplazo por KMS
real (AWS/GCP/Vault) es deliberadamente angosto: _cifrar_master() y
_descifrar_master() son las DOS unicas funciones que hay que cambiar por
kms_client.encrypt()/decrypt() -- cifrar_clave_sol()/descifrar_clave_sol()
y todo lo que las llama quedan iguales.
"""
import os
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from jose import jwt, JWTError
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Fix Fase R3: antes JWT_SECRET_KEY tenia un default hardcodeado que
# funcionaba igual en dev y en produccion -- si alguna vez se desplegaba sin
# fijar la variable de entorno, cualquiera podia forjar tokens validos para
# cualquier tenant con ese valor, que es publico (esta en este archivo).
# Ahora: en ENTORNO=prod, falta la variable = la app ni arranca. En dev seguimos
# permitiendo el fallback para no exigir configuracion extra en cada clon local.
ENTORNO = os.environ.get("ENTORNO", "dev")
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "")
if not JWT_SECRET_KEY:
    if ENTORNO == "prod":
        raise RuntimeError(
            "JWT_SECRET_KEY es obligatorio cuando ENTORNO=prod -- sin esto, "
            "cualquiera puede forjar tokens validos para cualquier tenant. "
            'Generar uno con: python -c "import secrets; print(secrets.token_urlsafe(64))"'
        )
    print(
        "[AVISO] JWT_SECRET_KEY no esta configurada -- usando un valor fijo de "
        "desarrollo (no usar en produccion, ver ENTORNO en .env.example)."
    )
    JWT_SECRET_KEY = "dev-secret-cambiar-en-produccion"
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", 1440))


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def crear_token(usuario_id: str, tenant_id: str) -> str:
    expira = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": usuario_id, "tenant_id": tenant_id, "exp": expira}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decodificar_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


def crear_token_ingreso_directo(
    usuario_id: str, tenant_id: str, empresa_id: str, minutos: int = 2, scope: str = "ingreso_directo"
) -> str:
    """
    Token de un solo proposito y vida MUY corta -- para el flujo de
    "ingreso directo a SUNAT" (ver routers/empresas.py). Hace falta
    porque esa pantalla se abre navegando derecho a una URL en una
    pestaña nueva, y una navegacion comun del navegador no manda el
    header Authorization -- asi que el token viaja como query param en
    su lugar. Vida corta (2 minutos por defecto, alcanza de sobra para
    que se abra la pestaña) y un "scope" propio para que, si alguien
    llegara a verlo en un log o en el historial del navegador, no sirva
    para nada mas que ese unico uso puntual. `scope` parametrizable
    porque hay mas de un destino de ingreso directo (Buzon/Menu SOL
    clasico vs. Mis Declaraciones y Pagos) -- cada uno con su propio
    scope, para que un token de uno no sirva para entrar al otro.
    """
    expira = datetime.now(timezone.utc) + timedelta(minutes=minutos)
    payload = {
        "sub": usuario_id,
        "tenant_id": tenant_id,
        "empresa_id": empresa_id,
        "scope": scope,
        "exp": expira,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


_dev_key_generada = None


def _fernet() -> Fernet:
    global _dev_key_generada
    key = os.environ.get("CREDENCIALES_FERNET_KEY", "")
    if not key:
        # No hay clave configurada: se genera una aleatoria SOLO para esta
        # ejecucion, para que el entorno local funcione sin configuracion
        # extra. Esto NO persiste entre reinicios (los datos cifrados con
        # ella dejan de poder leerse) -- sirve unicamente para desarrollo.
        # En cualquier ambiente real, CREDENCIALES_FERNET_KEY debe venir de
        # un secreto real, y en Fase 1 de KMS -- nunca de una clave generada
        # en memoria como esta.
        if _dev_key_generada is None:
            _dev_key_generada = Fernet.generate_key()
            print(
                "[AVISO] CREDENCIALES_FERNET_KEY no esta configurada -- usando "
                "una clave temporal solo para esta ejecucion (no usar en produccion)."
            )
        return Fernet(_dev_key_generada)
    return Fernet(key.encode() if isinstance(key, str) else key)


def _cifrar_master(datos: bytes) -> bytes:
    """
    Cifra con la clave maestra. PRODUCCION: reemplazar el cuerpo por una
    llamada real a KMS, por ejemplo (AWS):
        return boto3.client("kms").encrypt(KeyId=KMS_KEY_ID, Plaintext=datos)["CiphertextBlob"]
    """
    return _fernet().encrypt(datos)


def _descifrar_master(datos_cifrados: bytes) -> bytes:
    """PRODUCCION: reemplazar por boto3.client("kms").decrypt(CiphertextBlob=datos_cifrados)["Plaintext"]."""
    return _fernet().decrypt(datos_cifrados)


def cifrar_clave_sol(clave_en_claro: str) -> tuple[bytes, bytes]:
    """
    Envelope encryption. Devuelve (clave_cifrada, dek_cifrada) -- ambas se
    guardan en la fila de credenciales_sol (columnas clave_cifrada y
    dek_cifrada, que ya existian en el esquema desde la Fase 0).
    """
    dek = Fernet.generate_key()
    clave_cifrada = Fernet(dek).encrypt(clave_en_claro.encode("utf-8"))
    dek_cifrada = _cifrar_master(dek)
    return clave_cifrada, dek_cifrada


def descifrar_clave_sol(clave_cifrada: bytes, dek_cifrada: bytes) -> str:
    """Requiere las dos columnas guardadas por cifrar_clave_sol() -- desenvuelve la DEK y despues descifra."""
    dek = _descifrar_master(dek_cifrada)
    return Fernet(dek).decrypt(clave_cifrada).decode("utf-8")
