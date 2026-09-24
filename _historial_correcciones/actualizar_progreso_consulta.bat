@echo off
cd /d "%~dp0"

REM Aplica los cambios de este round:
REM  - Backend: nueva migracion 0009 (columna "etapa" en consultas_jobs) +
REM    el adaptador ahora reporta el avance real de la consulta manual
REM    (iniciando sesion, autenticando, leyendo estado del contribuyente,
REM    abriendo el buzon, leyendo mensajes, descargando documentos nuevos).
REM  - Frontend: el boton "Consultar" de cada tarjeta ahora muestra una
REM    barra de progreso con el % y la etapa mientras corre, en vez de
REM    solo "Consultando...".
REM  - Backend: mensaje de error del limite de 1 minuto ahora incluye el
REM    RUC exacto que esta bloqueado, para que quede claro que el limite es
REM    por empresa (otras empresas no se ven afectadas). Se confirmo con
REM    una prueba real que el limite YA estaba bien separado por RUC -- no
REM    habia ningun bug de bloqueo cruzado entre empresas distintas.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_progreso_consulta.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_progreso_consulta.log
echo ---------------------------------------
echo Abre http://localhost:3000/empresas con Ctrl+F5.
echo.
echo Cosas nuevas para revisar:
echo  1. Haz clic en "Consultar" de cualquier empresa -- ahora deberias ver
echo     un %% y una etiqueta ("Iniciando sesion...", "Leyendo mensajes...",
echo     etc.) con una barrita que avanza, en vez de solo "Consultando...".
echo  2. Si generas una Ficha RUC de una empresa y de inmediato generas la
echo     de OTRA empresa distinta, ya no deberia pedirte esperar (el limite
echo     de 1 minuto es por RUC). Si de casualidad te vuelve a pasar con dos
echo     RUCs realmente distintos, copia el mensaje de error exacto (ahora
echo     incluye el RUC) para revisarlo con evidencia concreta.
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Corriendo la migracion de base de datos (agrega etapa a consultas_jobs)...
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
echo Logs del frontend (debe decir "Ready"):
echo ---------------------------------------
docker-compose logs --tail=30 frontend

exit /b 0
