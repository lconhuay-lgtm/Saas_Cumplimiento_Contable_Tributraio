# Runbook de operaciones

Complementa a `PLAYBOOK_FALLOS_SUNAT.md` (ese es para "SUNAT cambió algo en su
portal"; este es para incidentes de infraestructura/secretos). Se arranca en
la Fase R5 del plan de remediación con la sección más urgente (pérdida de
secretos); las demás secciones (reinicio de servicios, escalado, plan de
contingencia del proveedor cloud) se agregan en la Fase D del despliegue.

## Dónde viven los secretos hoy

Tres secretos críticos: `CREDENCIALES_FERNET_KEY`, `JWT_SECRET_KEY`,
`POSTGRES_PASSWORD`. Corto plazo (hasta que haya presupuesto para KMS real,
ver más abajo): viven en el `.env` del servidor **y además** en una copia en
el gestor de contraseñas del equipo (Bitwarden/1Password/el que se use) —
nunca solo en un lugar. El `.env` del servidor sigue siendo necesario para
que la app arranque; el gestor de contraseñas es la copia de respaldo si se
pierde el servidor o el archivo.

Los secretos de PRODUCCIÓN (generados en la Fase R5, distintos de los que usa
el entorno de desarrollo) deben estar guardados en el gestor de contraseñas
del equipo antes de desplegar por primera vez — ver Fase D0 del plan de
remediación.

## Incidente: se perdió (o se sospecha comprometida) `CREDENCIALES_FERNET_KEY`

**Qué se pierde exactamente:** SOLO la capacidad de descifrar la columna
`credenciales_sol.clave_cifrada` (la contraseña SOL de cada empresa). Todo lo
demás -- `mensajes_buzon` (historial de notificaciones ya leídas),
`empresas`, `tenants`, `usuarios`, `tarea_obligaciones` -- **no depende de
esta clave y no se pierde**. El síntoma concreto: el worker no puede volver a
loguearse a SUNAT para NINGUNA empresa hasta que se resuelva esto (toda
consulta nueva falla al descifrar la clave SOL).

**Procedimiento:**

1. Antes de asumir que se perdió de verdad: revisar la copia en el gestor de
   contraseñas del equipo. Si está ahí, no es un incidente -- solo hay que
   volver a ponerla en el `.env` del servidor y reiniciar `backend`, `worker`
   y `scheduler` (los tres procesos deben compartir el mismo valor).
2. Si de verdad se perdió (no está en ningún lado): no hay forma de
   recuperar las contraseñas SOL ya cifradas -- es cifrado real, no hay
   puerta trasera. Generar una `CREDENCIALES_FERNET_KEY` nueva:
   ```
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. Poner la clave nueva en el `.env` de los tres procesos (backend, worker,
   scheduler) y reiniciarlos.
4. Borrar (o marcar como inválidas) todas las filas de `credenciales_sol`
   existentes -- quedarían con datos indescifrables con la clave nueva, y un
   intento de descifrado silenciosamente incorrecto es peor que un error
   claro de "faltan credenciales".
5. Avisar a cada tenant que debe volver a ingresar el usuario/clave SOL de
   cada una de sus empresas -- el historial de mensajes ya leídos sigue
   intacto y visible, solo se corta la posibilidad de hacer consultas nuevas
   hasta que recarguen sus credenciales.
6. Guardar la clave nueva en el gestor de contraseñas del equipo de
   inmediato, antes de seguir con cualquier otra cosa.

## Incidente: se perdió `JWT_SECRET_KEY`

Mucho menos grave: no hay pérdida de datos. Generar una nueva
(`python -c "import secrets; print(secrets.token_urlsafe(64))"`), ponerla en
el `.env` del backend y reiniciarlo. Efecto: todos los tokens JWT ya emitidos
quedan inválidos de inmediato (cada usuario tiene que volver a iniciar
sesión) -- ninguna otra consecuencia.

## Incidente: se perdió `POSTGRES_PASSWORD`

Si todavía hay acceso al contenedor/VM de Postgres, se puede cambiar
directamente (`ALTER USER buzon WITH PASSWORD '...'` dentro de `psql`) sin
tocar ningún dato. Solo es un incidente serio si además se perdió el acceso
al propio servidor -- en ese caso es un escenario de recuperación de
infraestructura, no de secretos (ver Fase D5 del plan: backups + restauración
en una VM nueva).

## Camino a mediano plazo: KMS real

`security.py` ya está preparado para esto -- `_cifrar_master()` y
`_descifrar_master()` son las únicas dos funciones que hay que reemplazar por
llamadas a un KMS real (AWS KMS, GCP KMS, Vault). Cuando eso pase, el
incidente de "se perdió la clave maestra" deja de ser posible del mismo modo
(el KMS gestiona la clave, con sus propias políticas de backup/rotación) --
no es bloqueante para el lanzamiento inicial, pero es la razón por la que la
Fase R5 solo pide una segunda copia manual, no una solución definitiva.
