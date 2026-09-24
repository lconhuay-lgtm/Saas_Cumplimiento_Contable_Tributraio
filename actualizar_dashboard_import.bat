@echo off
cd /d "%~dp0"

REM Reconstruye el stack con el dashboard nuevo y el importador de Excel.
REM No hay migraciones nuevas de base de datos esta vez (solo endpoints y
REM pantallas nuevas), asi que esto es mas rapido que las pruebas de
REM Fase 1/2.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_dashboard_import.log'"

echo.
echo ---------------------------------------
echo Resultado completo guardado en: %cd%\resultado_dashboard_import.log
echo ---------------------------------------
echo Abre http://localhost:3000/dashboard para ver el dashboard.
pause
exit /b 0

:main
echo ---------------------------------------
echo Reconstruyendo el stack (agrega pandas/openpyxl al backend para poder leer Excel)
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
echo ---------------------------------------
echo Estado de los servicios:
echo ---------------------------------------
docker-compose ps

echo.
echo ---------------------------------------
echo Todo listo. Ahora en el navegador:
echo ---------------------------------------
echo 1. Abre http://localhost:3000/dashboard (o entra normal y haz clic en "Dashboard")
echo 2. Ve a "Empresas" y haz clic en "Importar desde Excel"
echo 3. Sube tu archivo real, por ejemplo:
echo    J:\Automatiza_Sunat\Datos_Auto_SOL\Claves Sol_Brian.xls
echo 4. Deberia decir algo como "55 empresa(s) creada(s)"
echo    (si lo subes de nuevo despues, deberia decir "0 creadas, 55 ya existian" -- no duplica)

exit /b 0
