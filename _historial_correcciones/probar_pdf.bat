@echo off
cd /d "%~dp0"

REM Esta vez cambia el scraper (descarga de PDFs), el backend (nueva
REM columna + almacenamiento + endpoint) y el frontend (visor). La prueba
REM entra a SUNAT de verdad y descarga 2 documentos reales -- puede tardar
REM 1-3 minutos.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_pdf.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_pdf.log
echo ---------------------------------------
echo Si todo salio bien, abre http://localhost:3000 -> Empresas -> MISKY SONCO SAC
echo y prueba el boton "Ver PDF" en un mensaje reciente.
pause
exit /b 0

:main
echo ---------------------------------------
echo Reconstruyendo el stack (agrega boto3 al backend/worker)
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
echo Corriendo migraciones (agrega la columna documento_ref)...
docker-compose exec -T backend alembic upgrade head

echo.
echo ---------------------------------------
echo Probando el visor de PDF end-to-end
echo ---------------------------------------
set "PYEXE=C:\Users\LCK Business Advisor\AppData\Local\Programs\Python\Python314\python.exe"
"%PYEXE%" -m pip install requests -q
"%PYEXE%" probar_pdf.py

echo.
echo ---------------------------------------
echo Documentos guardados localmente (sunat_data\documentos\):
echo ---------------------------------------
dir /s /b "sunat_data\documentos\*.pdf" 2>nul

echo.
echo ---------------------------------------
echo Logs del worker (ultimas 200 lineas, por si algo fallo en la descarga):
echo ---------------------------------------
docker-compose logs --tail=200 worker

exit /b 0
