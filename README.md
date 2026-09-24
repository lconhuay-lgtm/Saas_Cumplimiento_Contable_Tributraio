# Buzón SUNAT — multi-RUC

Plataforma para revisar el Buzón Electrónico SOL de varias empresas desde un solo tablero, sin entrar a SUNAT una por una. Ver `Plan_Arquitectura_BuzonSUNAT_SaaS.md` (carpeta padre) para el roadmap completo.

## Estructura

```
buzon-saas/
├── docker-compose.yml       # Postgres + Redis + backend + worker + scheduler + frontend
├── .env.example              # Variables de entorno (copiar a .env)
├── core_scraper/             # El motor de automatización SUNAT (reutilizado, ya probado)
│   ├── config.py
│   ├── data_access.py
│   ├── web_navigation.py
│   └── adapter.py            # Interfaz unica: consultar_buzon(ruc, usuario, clave) -> mensajes[]
├── backend/                  # API FastAPI + worker + scheduler (misma imagen, distinto comando)
│   ├── Dockerfile             # Incluye Chromium + Xvfb (los usa el worker, no el backend/scheduler)
│   ├── requirements.txt
│   ├── worker_entry.py        # Arranca Xvfb + el worker RQ (con scheduler para el chequeo nocturno)
│   ├── scheduler_entry.py     # Proceso aparte: dispara el chequeo nocturno y el resumen diario por cron
│   ├── alembic/                # Migraciones de base de datos
│   └── app/
│       ├── main.py            # Punto de entrada de la API
│       ├── database.py        # Conexión a Postgres
│       ├── models.py          # Tablas (SQLAlchemy)
│       ├── schemas.py         # Validación de requests/responses (Pydantic)
│       ├── security.py        # Hash de contraseñas, JWT, envelope encryption
│       ├── queue_conn.py       # Conexión a Redis / cola RQ
│       ├── rate_limit.py       # Límite por RUC + semáforo global de sesiones SUNAT
│       ├── jobs.py             # Lo que ejecuta el worker: consulta el buzón y guarda mensajes
│       ├── email_utils.py      # Correo de resumen diario + alerta/recuperación del canario
│       ├── scheduler_job.py    # Chequeo nocturno + resumen diario + chequeo canario (Fase 3)
│       └── routers/
│           ├── auth.py         # Registro y login
│           ├── empresas.py     # CRUD de empresas + conteo de pendientes + importar desde Excel + marcar canario
│           ├── consultas.py    # Encolar consulta / estado / mensajes / marcar leído
│           ├── admin.py        # Chequeo nocturno/resumen manuales + panel de salud (Fase 3)
│           └── dashboard.py    # Resumen general (pendientes totales, actividad reciente)
├── PLAYBOOK_FALLOS_SUNAT.md  # Fase 3: qué revisar primero cuando SUNAT cambia algo en su portal
└── frontend/                 # Tablero web (Next.js)
    ├── Dockerfile
    ├── lib/api.js              # Cliente único de la API (JWT en localStorage)
    ├── components/Sidebar.js   # Navegación (Dashboard / Empresas / Salud del sistema) + perfil
    └── app/
        ├── login/, registro/   # Auth
        ├── dashboard/          # Resumen general, pantalla de aterrizaje tras login
        ├── empresas/           # Lista de empresas, conteo de pendientes, "consultar en vivo", importar Excel
        ├── empresas/[id]/      # Detalle: mensajes, marcar leído, marcar como cuenta canario
        └── salud/              # Fase 3: tasa de éxito del canario por flujo + errores recientes
```

## Por qué está separado así

`core_scraper/` es el motor que ya está probado en `Sunat_Aut_Brian/web_navigation.py` — la parte que sabe loguearse en SUNAT SOL y leer el buzón. Vive aparte del backend a propósito: es la pieza más frágil (se rompe cuando SUNAT cambia su portal, como pasó esta semana) y es la única que corre dentro del `worker`, no del `backend` — así una consulta lenta o colgada nunca bloquea la API.

`backend` y `worker` son la **misma imagen Docker**, solo con comandos distintos (`uvicorn ...` vs `rq worker ...`). Eso evita mantener dos Dockerfiles a costa de que el backend cargue Chromium sin usarlo — aceptable por ahora, se puede separar en imágenes distintas más adelante si el tamaño de la imagen importa.

## Cómo funciona una consulta en vivo

1. El tablero llama a `POST /empresas/{id}/consultar`.
2. El backend valida el límite por RUC (no más de una consulta por minuto al mismo RUC — configurable), crea una fila en `consultas_jobs` con estado `pendiente`, y la encola en Redis. Responde al instante con el `job_id` (no espera a que termine).
3. El `worker` toma el job de la cola, espera su turno en el semáforo global (máximo N sesiones de SUNAT en paralelo, configurable), y llama a `core_scraper/adapter.py` para loguearse y leer el buzón — con reintentos si falla.
4. Los mensajes nuevos se guardan en `mensajes_buzon` (la restricción única evita duplicados si se vuelve a consultar). El job pasa a `completado` o `error`.
5. El tablero hace *polling* a `GET /jobs/{job_id}` hasta ver el resultado, o lee directamente `GET /empresas/{id}/mensajes` para el historial ya guardado.

## Cómo funciona el chequeo nocturno + resumen por correo (Fase 2)

1. `scheduler` (proceso aparte, `scheduler_entry.py`) dispara todos los días, por cron: primero el chequeo nocturno, más tarde el resumen.
2. El chequeo nocturno (`encolar_chequeo_nocturno` en `scheduler_job.py`) recorre las empresas activas de todos los tenants activos y encola su consulta con `enqueue_in()`, espaciadas ~45s entre sí (para no parecer tráfico sospechoso ante SUNAT) — no bloquea nada mientras espera, RQ se encarga de moverlas a la cola cuando les toca.
3. Cada consulta corre exactamente igual que una manual (mismo `jobs.py`, mismo rate limiting, mismos reintentos) y guarda los mensajes nuevos.
4. Más tarde, el resumen (`enviar_resumenes_diarios`) busca los jobs completados con mensajes nuevos que todavía no se avisaron, los agrupa por tenant, y le manda un correo a cada usuario — o, si no hay SMTP configurado, guarda el contenido como archivo de texto en `sunat_data/emails_dev/` (ver `email_utils.py`).
5. Los endpoints `POST /admin/chequeo-nocturno` y `POST /admin/enviar-resumenes` disparan ambos pasos manualmente, sin esperar al horario programado — así se prueban sin tener que esperar a la madrugada.

## Cómo funciona el chequeo canario y el panel de salud (Fase 3)

La motivación es concreta: nos enteramos de que SUNAT había cambiado su portal por los reclamos de los clientes, no por nuestro propio sistema. El chequeo canario existe para que eso no se repita.

1. Se marca **una** empresa (una cuenta de prueba, nunca la de un cliente real) con `es_canario=True` desde su página de detalle en el tablero.
2. `scheduler` dispara `ejecutar_chequeo_canario()` cada `CANARIO_INTERVALO_MIN` minutos (30 por defecto). Es un login de prueba completo contra SUNAT — usa exactamente el mismo `adapter.consultar_buzon()` que las consultas reales — pero **no crea `ConsultaJob`, no guarda mensajes ni descarga documentos, y no toca los datos visibles de la empresa** (razón social, condición de domicilio, etc.). Solo mide: ¿el login sigue funcionando?, ¿cuánto tarda?, ¿qué pantalla post-login mostró SUNAT esta vez (`flujo_detectado`)? Todo eso se guarda en `canario_checks`, separado por completo de las tablas que ve un cliente.
3. Si se acumulan `CANARIO_FALLOS_CONSECUTIVOS_PARA_ALERTA` fallos seguidos (2 por defecto), se manda un correo de alerta a `ALERTA_CANARIO_EMAIL` — y cuando vuelve a tener éxito después de eso, un correo de "se recuperó". Una bandera en Redis (no una tabla nueva) evita repetir el mismo aviso mientras el problema sigue activo.
4. `GET /admin/salud` junta, para el período elegido, la tasa de éxito y duración promedio del canario **desglosada por flujo detectado** (una señal temprana de cambio de portal, antes de que algo se rompa del todo) más la tasa de éxito de las consultas normales — a propósito por separado, porque pueden fallar por razones distintas. `GET /admin/errores-recientes` lista los últimos fallos de ambos tipos. La página **Salud del sistema** del tablero muestra todo esto, con un botón para correr el canario a mano sin esperar al intervalo programado.
5. Ver `PLAYBOOK_FALLOS_SUNAT.md` para el proceso completo de diagnóstico cuando llega una alerta.

## Cómo levantarlo (desarrollo local)

1. Copiar `.env.example` a `.env`. **Importante:** generar una `CREDENCIALES_FERNET_KEY` real (no dejarla vacía) con:
   ```
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   Backend, worker y scheduler son procesos distintos y deben compartir esta clave.
2. `docker-compose up --build` (la primera vez tarda varios minutos: instala Chromium en la imagen del backend/worker/scheduler, y las dependencias de Next.js en la del frontend).
3. Migraciones: `docker-compose exec backend alembic upgrade head`
4. Tablero web: http://localhost:3000
5. Documentación interactiva de la API: http://localhost:8000/docs
6. Logs del worker en vivo (útil para ver el navegador trabajando): `docker-compose logs -f worker`
7. Logs del scheduler (para ver los horarios programados): `docker-compose logs -f scheduler`

## Seguridad de credenciales (envelope encryption)

Cada credencial SOL se cifra con su propia clave (DEK) generada al azar; esa DEK se cifra a su vez con una "clave maestra" (`CREDENCIALES_FERNET_KEY`). En producción, la clave maestra deja de ser una variable de entorno y pasa a ser KMS real (AWS/GCP/Vault) — el cambio queda acotado a dos funciones en `security.py` (`_cifrar_master` / `_descifrar_master`), todo lo demás queda igual.

## Estado

**Fase 0 (semanas 1-2) — completa y verificada.**
- [x] Esquema de base de datos (6 tablas).
- [x] `core_scraper` extraído como paquete independiente.
- [x] Modelos SQLAlchemy + migraciones Alembic.
- [x] Registro de tenant + usuario admin, login con JWT.
- [x] CRUD de empresas con aislamiento multi-tenant probado.

**Fase 1 (semanas 3-5) — completa y verificada contra SUNAT real.**
- [x] Adaptador `consultar_buzon()` reutilizando el motor ya probado.
- [x] Worker con Chromium + Xvfb (pantalla virtual, necesaria porque SUNAT bloquea Chrome headless) + cola de trabajos (RQ sobre Redis).
- [x] Endpoints para encolar consultas y ver estado/resultado.
- [x] Rate limiting por RUC + semáforo global de sesiones concurrentes + reintentos con backoff.
- [x] Envelope encryption real para las credenciales SOL.
- [x] Prueba end-to-end contra SUNAT real: login real, navegación, 19 mensajes leídos y guardados sin duplicados.

**Fase 2 (semanas 6-8) — completa y verificada en la máquina real.**
- [x] Tablero web (Next.js): login/registro, lista de empresas con conteo de pendientes, "consultar en vivo", detalle de mensajes.
- [x] Historial persistido: mensajes guardados en Postgres desde Fase 1, ahora con marcar leído/no leído y "marcar todos".
- [x] Pausar/reactivar una empresa sin borrar su historial ni credenciales.
- [x] Chequeo nocturno programado (`scheduler`, vía cron) que recorre empresas activas y encola sus consultas espaciadas en el tiempo.
- [x] Correo de resumen diario, con modo prueba (archivo de texto) cuando no hay SMTP configurado.
- [x] Endpoints `/admin` para disparar el chequeo nocturno y el resumen manualmente, sin esperar al cron.
- [x] Prueba end-to-end en la máquina real: login real, chequeo nocturno, correo de resumen.

**Fase 3, semanas 9-10 (confiabilidad y observabilidad) — completa y verificada con pruebas automatizadas (login real a SUNAT pendiente de correr en la máquina real).**
- [x] Modelo `CanarioCheck` + columna `Empresa.es_canario`, con migración probada (cadena completa `0001` → `0010`).
- [x] `flujo_detectado` instrumentado en `web_navigation.py` y devuelto por `adapter.consultar_buzon()` en las 5 ramas de retorno, como señal temprana de cambios en el portal.
- [x] `ejecutar_chequeo_canario()` + `_evaluar_alerta_canario()`: login de prueba periódico, separado por completo de las consultas de tenants, con alerta/recuperación por correo vía una bandera en Redis (evita repetir el aviso). 13/13 escenarios probados con `fakeredis` + SQLite + adaptador simulado.
- [x] Chequeo canario cablado en `scheduler_entry.py` cada `CANARIO_INTERVALO_MIN` minutos (30 por defecto), verificado registrando los 5 jobs en una instancia real de APScheduler.
- [x] Endpoints `GET /admin/salud`, `GET /admin/errores-recientes`, `POST /admin/canario/ejecutar`, y `PATCH /empresas/{id}` extendido para marcar/desmarcar `es_canario` — 21/21 aserciones probadas contra la API real (FastAPI `TestClient`).
- [x] Página **Salud del sistema** en el tablero (tasa de éxito por flujo, duración promedio, errores recientes, botón para correr el canario a mano) + botón "Marcar como cuenta canario" en el detalle de cada empresa.
- [x] `PLAYBOOK_FALLOS_SUNAT.md`: qué revisar primero cuando llega una alerta del canario.
- [ ] Prueba end-to-end contra SUNAT real (login real de la cuenta canario, alerta/recuperación por correo real) — pendiente de correr en la máquina real, igual que las demás fases.

**Mejoras post-Fase 2 (a pedido, no estaban en el plan original de 16 semanas).**
- [x] Dashboard: resumen general (pendientes totales, empresas activas, empresas con pendientes, actividad reciente) como pantalla de aterrizaje del tablero.
- [x] Importar empresas desde Excel: botón en el tablero que sube el mismo archivo de credenciales que ya usa la automatización (columnas RUC/usuario/clave/razón social), crea las que faltan y salta las que ya existen. Probado contra el archivo real de 55 empresas.
- [x] Empresas como tarjetas: cada una muestra razón social, RUC, estado, y chips de pendientes/notificaciones totales/consultas realizadas.
- [x] Rediseño visual (Tailwind CSS + lucide-react): paleta esmeralda corporativo, tipografía con jerarquía marcada, sombras sutiles, microinteracciones.
- [x] Visor de PDF: el worker descarga el documento de cada mensaje nuevo (reutilizando la lógica de descarga ya probada del motor original) dentro de la misma sesión de SUNAT, y el tablero lo muestra en un visor integrado.

## Visor de PDF: cómo funciona y cómo migrar a producción

Cuando el worker encuentra un mensaje nuevo, hace clic en él (dentro de la misma sesión ya autenticada) y descarga su documento con `_descargar_documento_constancia()` — el método que ya usaba la automatización original, sin reescribir esa lógica. Un fallo descargando el documento nunca tumba la consulta: el mensaje se guarda igual, solo queda sin botón "Ver PDF" hasta la próxima consulta.

El documento se guarda a través de `backend/app/almacenamiento.py`, que tiene dos modos intercambiables por variable de entorno (`ALMACENAMIENTO_MODO`):

- **local** (default): guarda el PDF en `sunat_data/documentos/` — cero configuración extra, pensado para desarrollo. El volumen real esperado (unas pocas decenas de empresas, algunas notificaciones al mes cada una) es de apenas unos GB al año, así que no hace falta nada más sofisticado mientras se use así.
- **s3**: sube el PDF a un bucket compatible con la API de S3. Pensado para **Cloudflare R2** en producción (sin costo de egreso nunca, 10GB gratis al mes, luego $0.015/GB-mes) — para activarlo, cambiar `ALMACENAMIENTO_MODO=s3` en `.env` y llenar `S3_BUCKET`, `S3_ENDPOINT_URL` (la URL de tu cuenta R2), `S3_ACCESS_KEY`, `S3_SECRET_KEY`. No hace falta cambiar nada del código: la misma API de `boto3` sirve para R2, AWS S3, o Backblaze B2 si se prefiere alguno de esos.

El visor del tablero pide el PDF con `fetch()` (usando el token de sesión) en vez de apuntar un `<iframe>` directo al backend, porque un iframe no manda el header `Authorization` — arma una blob URL con la respuesta y esa es la que ve el visor.
