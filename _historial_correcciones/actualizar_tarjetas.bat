@echo off
cd /d "%~dp0"

REM Esta vez cambio tanto backend (2 campos nuevos en /empresas) como
REM frontend (empresas como tarjetas), asi que reconstruye los dos. -V seve
REM sigue siendo necesario para el frontend por el mismo motivo de la vez
REM pasada (volumen anonimo de node_modules).

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_tarjetas.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_tarjetas.log
echo ---------------------------------------
echo Abre http://localhost:3000/empresas (Ctrl+F5 si ya lo tenias abierto).
pause
exit /b 0

:main
echo ---------------------------------------
echo Reconstruyendo backend + frontend
echo ---------------------------------------
docker-compose build
if errorlevel 1 (
    echo ERROR: docker-compose build fallo. Verifica que Docker Desktop este abierto.
    exit /b 1
)

docker-compose up -d --force-recreate -V
if errorlevel 1 (
    echo ERROR: docker-compose up fallo. Verifica que Docker Desktop este abierto.
    exit /b 1
)

echo.
echo Esperando a que todo arranque...
ping -n 16 127.0.0.1 >nul

echo.
echo ---------------------------------------
echo Estado de los servicios:
echo ---------------------------------------
docker-compose ps

exit /b 0
