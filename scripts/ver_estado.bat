@echo off
cd /d "%~dp0.."

REM Este script NO toca SUNAT -- solo mira que quedo corriendo y que paso
REM en la ultima corrida. Seguro de correr cuantas veces haga falta.

call :main > estado_actual.log 2>&1
type estado_actual.log

echo.
echo ---------------------------------------
echo Guardado en: %cd%\estado_actual.log
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Contenedores actuales
echo ---------------------------------------
docker-compose ps

echo.
echo ---------------------------------------
echo Salud de la API
echo ---------------------------------------
curl -s http://localhost:8000/health

echo.
echo.
echo ---------------------------------------
echo Log completo del worker desde que arranco
echo ---------------------------------------
docker-compose logs worker

exit /b 0
