@echo off
cd /d "%~dp0"

REM Igual que probar_fase1.bat: el progreso se muestra EN VIVO en esta
REM ventana (con Tee-Object) y a la vez queda guardado en
REM resultado_fase2.log. La primera vez tarda mas porque hay que descargar
REM las dependencias del tablero (Next.js/React) ademas de reconstruir el
REM backend -- varios minutos es normal. La parte de "chequeo nocturno real"
REM entra a SUNAT de verdad, asi que puede tardar otro minuto mas.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_fase2.log'"

echo.
echo ---------------------------------------
echo Resultado completo guardado en: %cd%\resultado_fase2.log
echo ---------------------------------------
echo Si todo salio bien, abre http://localhost:3000 en tu navegador para ver el tablero.
pause
exit /b 0

:main
echo ---------------------------------------
echo Fase 2 - Reconstruyendo el stack (ahora incluye el tablero web y el scheduler, tarda mas la primera vez)
echo ---------------------------------------
docker-compose build
if errorlevel 1 (
    echo ERROR: docker-compose build fallo. Verifica que Docker Desktop este abierto.
    exit /b 1
)

docker-compose up -d --force-recreate
if errorlevel 1 (
    echo ERROR: docker-compose up fallo. Verifica que Docker Desktop este abierto.
    exit /b 1
)

echo.
echo Esperando a que todo este listo...
ping -n 16 127.0.0.1 >nul

echo.
echo Corriendo migraciones (agrega la columna 'notificado' de Fase 2)...
docker-compose exec -T backend alembic upgrade head

echo.
echo ---------------------------------------
echo Probando Fase 2 end-to-end
echo ---------------------------------------
set "PYEXE=C:\Users\LCK Business Advisor\AppData\Local\Programs\Python\Python314\python.exe"
"%PYEXE%" -m pip install requests pandas xlrd -q
"%PYEXE%" probar_fase2.py

echo.
echo ---------------------------------------
echo Correos de prueba generados (modo prueba, sin SMTP configurado):
echo ---------------------------------------
dir /b /o-d "sunat_data\emails_dev\*.txt" 2>nul

echo.
echo ---------------------------------------
echo Estado de todos los servicios:
echo ---------------------------------------
docker-compose ps

echo.
echo ---------------------------------------
echo Logs del scheduler (deberia mostrar que arranco y sus horarios programados):
echo ---------------------------------------
docker-compose logs --tail=30 scheduler

echo.
echo ---------------------------------------
echo Logs del worker (por si algo fallo en la consulta real):
echo ---------------------------------------
docker-compose logs --tail=150 worker

exit /b 0
