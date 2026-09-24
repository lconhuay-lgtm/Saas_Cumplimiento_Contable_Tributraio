@echo off
cd /d "%~dp0"

REM Este script tarda varios minutos (build de Docker + prueba real contra
REM SUNAT). Todo lo que corre en :main se muestra EN VIVO en esta ventana
REM (con Tee-Object) Y a la vez se guarda en resultado_fase1.log. Asi ves
REM el progreso mientras corre, y si la ventana se cierra sola, el
REM resultado completo queda guardado en un archivo de texto que se puede
REM abrir despues (o mandarle a Claude para que lo revise).
REM
REM Si la pantalla se queda negra sin mostrar nada por un rato largo, no
REM esta colgado: docker-compose build puede tardar varios minutos la
REM primera vez, y la prueba de login espera hasta 200 segundos.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_fase1.log'"

echo.
echo ---------------------------------------
echo Resultado completo guardado en: %cd%\resultado_fase1.log
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Fase 1 - Reconstruyendo el stack (incluye Chromium en la imagen, tarda mas la primera vez)
echo ---------------------------------------
docker-compose build
if errorlevel 1 (
    echo ERROR: docker-compose build fallo. Verifica que Docker Desktop este abierto.
    exit /b 1
)

REM --force-recreate es clave: sin esto, si el codigo cambio pero Compose no
REM detecta que hace falta un contenedor nuevo, el worker se queda corriendo
REM con el codigo viejo cargado en memoria aunque el archivo en disco ya
REM haya cambiado.
docker-compose up -d --force-recreate
if errorlevel 1 (
    echo ERROR: docker-compose up fallo. Verifica que Docker Desktop este abierto.
    exit /b 1
)

echo.
echo Esperando a que todo este listo...
REM "timeout" normal falla dentro de un pipeline (Tee-Object) porque pide
REM una consola real para el conteo -- se usa "ping" como espera en su lugar.
ping -n 13 127.0.0.1 >nul

echo.
echo Corriendo migraciones (por si hay alguna nueva)...
docker-compose exec -T backend alembic upgrade head

echo.
echo ---------------------------------------
echo Probando Fase 1 end-to-end (consulta real a SUNAT)
echo ---------------------------------------
set "PYEXE=C:\Users\LCK Business Advisor\AppData\Local\Programs\Python\Python314\python.exe"
"%PYEXE%" -m pip install requests pandas xlrd -q
"%PYEXE%" probar_fase1.py

echo.
echo ---------------------------------------
echo Logs del worker (desde que arranco el contenedor):
echo ---------------------------------------
docker-compose logs --tail=300 worker

echo.
echo ---------------------------------------
echo Si hubo un error, deberia haber una captura de pantalla aqui:
echo ---------------------------------------
dir /b /o-d "sunat_data\logs\error_*.png" 2>nul

exit /b 0
