# Playbook: "SUNAT cambió algo, ¿qué se revisa primero?"

Esta guía existe para no repetir, cada vez a ciegas, el mismo proceso de diagnóstico manual que se usó una y otra vez durante el desarrollo (capturar HTML en el momento de la falla, compararlo contra la última versión que funcionaba, ajustar un selector). El chequeo canario (Fase 3) existe justamente para que el primer síntoma de un cambio en el portal de SUNAT lo detecte este sistema — no el reclamo de un cliente.

## 0. Cómo te enterás

- Correo automático: "Buzón SUNAT -- ALERTA: el chequeo canario está fallando" (se manda cuando el canario acumula `CANARIO_FALLOS_CONSECUTIVOS_PARA_ALERTA` fallos seguidos, por defecto 2). Llega a `ALERTA_CANARIO_EMAIL`.
- O lo notás vos mismo en la página **Salud del sistema** del tablero (banner rojo si `en_alerta`).

Cuando llegue esa alerta (o notes fallos en consultas de clientes), seguí estos pasos en orden.

## 1. Confirmar si es un cambio real de SUNAT o un problema puntual

Abrí la página **Salud del sistema** (o `GET /admin/salud`):

- ¿El canario está en alerta? ¿Cuántos chequeos fallaron?
- ¿La tasa de éxito bajó en **todos** los flujos (`por_flujo`), o solo en uno?
- Revisá `GET /admin/errores-recientes`: ¿los errores son solo del canario, solo de consultas de clientes, o ambos?
  - **Solo 1-2 empresas fallan, el resto sigue bien** → probablemente NO es un cambio de SUNAT. Revisar esa empresa puntual primero (credenciales vencidas, RUC dado de baja, cuenta bloqueada por intentos fallidos en SUNAT, etc.).
  - **El canario también falla** (una cuenta controlada, sin ningún problema de credenciales) → es mucho más probable que sea un cambio real del portal.

## 2. Confirmar en qué paso del flujo se rompe

Cada `CanarioCheck` y `ConsultaJob` fallido guarda:

- `flujo_detectado` (o `etapa`, en el caso de `ConsultaJob`): en qué punto del login/navegación llegó antes de fallar (`flujo1`, `flujo2`, `sin_flujo`, o la etapa: `iniciando_sesion`, `autenticando`, `leyendo_estado`, `abriendo_buzon`, `leyendo_mensajes`, `descargando_documentos`).
- `error`: el mensaje de excepción de Selenium (`TimeoutException`, `NoSuchElementException`, etc.), que casi siempre indica un selector que ya no encuentra el elemento esperado.

Para el traceback completo (más detalle que el mensaje corto guardado en la BD):

```
docker-compose logs -f worker       # consultas normales
docker-compose logs -f scheduler    # chequeo canario y chequeo nocturno
```

## 3. Capturar evidencia HTML en el momento de la falla

Mismo proceso usado repetidamente durante el desarrollo: cuando un selector falla, lo más útil es tener el HTML real de la página en ese instante, para comparar contra el HTML de la última vez que funcionó.

- Si no hay una captura reciente, correr el canario a mano genera una fresca sin afectar a ningún cliente:
  - Botón **"Ejecutar chequeo canario ahora"** en la página Salud del sistema, o
  - `POST /admin/canario/ejecutar`
- Si todavía no hay ninguna empresa marcada como cuenta canario, marcar una de prueba (nunca la cuenta real de un cliente) desde su página de detalle → botón "Marcar como cuenta canario".

## 4. Comparar contra la última versión que funcionaba

- Buscar el último `CanarioCheck` exitoso antes de que empezaran los fallos: ¿cambió el `flujo_detectado` típico (por ejemplo, de `flujo1` a `sin_flujo`)? Eso apunta a que SUNAT cambió qué pantalla muestra después del login.
- Si el error es un selector no encontrado, inspeccionar el HTML capturado en el paso 3 y ubicar el selector correspondiente en `core_scraper/web_navigation.py` (login, `_click_condicional`, lectura del buzón) o `core_scraper/adapter.py`.

## 5. Aplicar el fix y verificarlo sin afectar a los tenants

1. Corregir el selector/flujo en `web_navigation.py` o `adapter.py`.
2. Probar **solo contra la cuenta canario** (`POST /admin/canario/ejecutar`) — nunca contra una empresa de un cliente real como primera prueba.
3. Confirmar 2-3 chequeos canario exitosos seguidos antes de considerar el fix listo.

## 6. Reconstruir y desplegar

Seguir el patrón ya establecido del proyecto: script `.bat` que hace `docker-compose exec backend alembic upgrade head` (si hubo migración) + `docker-compose restart backend worker scheduler frontend`, y after eso tailear los logs para confirmar que arrancó bien.

## 7. Confirmar la recuperación

- El correo **"el chequeo canario se RECUPERÓ"** debería llegar automáticamente en cuanto el canario vuelva a tener éxito después de haber estado en alerta (no hace falta hacer nada manual para esto).
- Revisar **Salud del sistema** para confirmar que la tasa de éxito por flujo volvió a subir, tanto del canario como de las consultas normales.

## Dónde mirar primero (resumen rápido)

1. Página **Salud del sistema** (`GET /admin/salud`) — pantallazo general.
2. `GET /admin/errores-recientes` — lista de errores recientes, canario y consultas mezclados.
3. `docker-compose logs -f worker` / `docker-compose logs -f scheduler` — traceback completo.
4. Captura HTML en el punto de falla (correr el canario a mano si hace falta una fresca).

## Sobre el logging centralizado

Los errores ya no viven solo en logs locales del contenedor: cada fallo (canario o consulta normal) se guarda en Postgres (`canario_checks.error`, `consultas_jobs.error`) y es consultable sin reproducir el error manualmente, vía `GET /admin/errores-recientes` y `GET /admin/salud` — esa es la centralización mínima que pedía la Fase 3. `docker-compose logs` sigue siendo necesario para el traceback completo (estos endpoints solo guardan el mensaje corto de la excepción), y si el volumen de empresas/errores crece mucho, el siguiente paso natural sería un agregador dedicado (Loki, Sentry, o similar) en vez de seguir leyendo logs de Docker a mano.
