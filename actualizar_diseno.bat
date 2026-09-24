@echo off
cd /d "%~dp0"

REM Solo cambia el frontend (Tailwind CSS + lucide-react + rediseno de
REM todas las pantallas) -- no toca el backend, worker, ni la base de
REM datos, asi que esto es rapido. La primera vez igual tarda un par de
REM minutos porque instala Tailwind/lucide-react en el contenedor.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_diseno.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_diseno.log
echo ---------------------------------------
echo Abre http://localhost:3000/dashboard para ver el nuevo diseno.
echo Si el navegador ya estaba abierto, refresca con Ctrl+F5 (recarga forzada).
pause
exit /b 0

:main
echo ---------------------------------------
echo Reconstruyendo el frontend (Tailwind CSS + lucide-react + rediseno)
echo ---------------------------------------
docker-compose build frontend
if errorlevel 1 (
    echo ERROR: docker-compose build fallo. Verifica que Docker Desktop este abierto.
    exit /b 1
)

REM -V (renovar volumenes anonimos) es clave aca: sin esto, Docker Compose
REM reutiliza el volumen anonimo viejo de node_modules (el de antes de
REM agregar Tailwind/lucide-react) encima de la imagen nueva, y el
REM contenedor arranca como si nunca se hubiera instalado nada nuevo --
REM exactamente el error "Module not found: Can't resolve 'lucide-react'".
docker-compose up -d --force-recreate -V frontend
if errorlevel 1 (
    echo ERROR: docker-compose up fallo. Verifica que Docker Desktop este abierto.
    exit /b 1
)

echo.
echo Esperando a que el frontend arranque...
ping -n 11 127.0.0.1 >nul

echo.
echo ---------------------------------------
echo Logs del frontend (deberia decir "Ready" sin errores):
echo ---------------------------------------
docker-compose logs --tail=60 frontend

exit /b 0
