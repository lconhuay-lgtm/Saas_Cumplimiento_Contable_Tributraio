@echo off
cd /d "%~dp0"

REM Agrega deteccion de cambios por "polling" al frontend (Docker Desktop en
REM Windows no siempre avisa al contenedor cuando un archivo cambia) y
REM recrea el contenedor para que la nueva configuracion tome efecto. Con
REM esto, las proximas veces que edite el frontend NO deberias necesitar
REM reiniciar nada -- el cambio deberia aparecer solo en unos segundos.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_hotreload.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_hotreload.log
echo ---------------------------------------
echo Espera unos 15 segundos despues de que termine, despues abre
echo http://localhost:3000/empresas con Ctrl+F5.
pause
exit /b 0

:main
echo ---------------------------------------
echo Recreando el frontend con deteccion de cambios por polling
echo ---------------------------------------
docker-compose up -d --force-recreate frontend

echo.
echo Esperando a que next dev arranque...
ping -n 11 127.0.0.1 >nul

echo.
echo ---------------------------------------
echo Logs del frontend (debe decir "Ready"):
echo ---------------------------------------
docker-compose logs --tail=40 frontend

exit /b 0
