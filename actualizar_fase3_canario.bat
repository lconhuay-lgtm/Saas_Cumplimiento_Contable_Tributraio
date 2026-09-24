@echo off
cd /d "%~dp0"

REM Fase 3 (confiabilidad y observabilidad, semanas 9-10 del roadmap):
REM chequeo "canario" -- un login de prueba periodico contra una cuenta
REM controlada, separado por completo de las consultas de los tenants, para
REM enterarnos de un cambio en el portal de SUNAT por nuestro propio
REM monitoreo, no por el reclamo de un cliente (como paso antes).
REM
REM Cambios incluidos:
REM  - Nueva migracion 0010 (Empresa.es_canario + tabla canario_checks).
REM  - core_scraper: web_navigation.py y adapter.py ahora reportan
REM    flujo_detectado (que pantalla post-login mostro SUNAT esta vez).
REM  - Backend: scheduler_job.ejecutar_chequeo_canario() + alerta/recuperacion
REM    por correo (via Redis, sin repetir el aviso mientras el problema sigue
REM    activo). Cableado en scheduler_entry.py cada CANARIO_INTERVALO_MIN
REM    minutos (30 por defecto).
REM  - Backend: endpoints GET /admin/salud, GET /admin/errores-recientes,
REM    POST /admin/canario/ejecutar, y PATCH /empresas/{id} ahora acepta
REM    es_canario.
REM  - Frontend: pagina nueva "Salud del sistema" (tasa de exito por flujo,
REM    duracion promedio, errores recientes, boton para correr el canario a
REM    mano) + boton "Marcar como cuenta canario" en el detalle de empresa.
REM  - PLAYBOOK_FALLOS_SUNAT.md: que revisar primero cuando llega una alerta.
REM
REM Todo esto se probo con pruebas automatizadas (fakeredis + SQLite +
REM adaptador simulado + FastAPI TestClient) -- lo que falta es la prueba
REM real contra SUNAT, que es lo que este script prepara.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_fase3_canario.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_fase3_canario.log
echo ---------------------------------------
echo.
echo Como probarlo:
echo  1. Abre http://localhost:3000/empresas y entra al detalle de UNA
echo     empresa que uses solo de prueba (nunca la de un cliente real) --
echo     ahi arriba deberia verse un boton "Marcar como cuenta canario".
echo     Haz clic para activarlo.
echo  2. Abre http://localhost:3000/salud (o el enlace "Salud del sistema"
echo     en el menu de la izquierda). Deberia decir que SI hay una empresa
echo     canario, con 0 chequeos todavia.
echo  3. En esa misma pagina, haz clic en "Ejecutar chequeo canario ahora" --
echo     esto corre un login real contra SUNAT con esa cuenta (tarda lo
echo     mismo que una consulta normal). Al terminar deberia aparecer un
echo     chequeo exitoso (o el error real, si algo fallo).
echo  4. Repite el chequeo 2 veces con una clave incorrecta a proposito (por
echo     ejemplo, cambia momentaneamente la clave SOL de esa empresa) para
echo     confirmar que llega el correo de alerta -- si no configuraste SMTP
echo     en .env, el correo queda guardado como archivo de texto en
echo     sunat_data\emails_dev\ en vez de enviarse de verdad.
echo  5. Vuelve a poner la clave correcta y corre el chequeo una vez mas --
echo     deberia llegar el correo de "se recupero".
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Corriendo la migracion de base de datos (agrega es_canario + canario_checks)...
echo ---------------------------------------
docker-compose exec -T backend alembic upgrade head

echo.
echo ---------------------------------------
echo Reiniciando backend, worker, scheduler y frontend
echo ---------------------------------------
docker-compose restart backend worker scheduler frontend

echo.
echo Esperando a que levanten...
ping -n 11 127.0.0.1 >nul

echo.
echo ---------------------------------------
echo Logs del backend (ultimas 15 lineas):
echo ---------------------------------------
docker-compose logs --tail=15 backend

echo.
echo ---------------------------------------
echo Logs del scheduler (deberia mencionar "Chequeo canario cada X minutos"):
echo ---------------------------------------
docker-compose logs --tail=20 scheduler

echo.
echo ---------------------------------------
echo Logs del frontend (debe decir "Ready"):
echo ---------------------------------------
docker-compose logs --tail=30 frontend

exit /b 0
