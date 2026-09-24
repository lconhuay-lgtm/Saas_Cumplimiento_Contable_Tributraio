@echo off
cd /d "%~dp0"

REM Solo cambio backend (nuevos campos/endpoints) y frontend (que ya se
REM autorecarga desde el fix anterior). El backend tiene --reload asi que
REM en teoria tampoco necesita reinicio, pero por las dudas se reinicia
REM igual -- es rapido, no reconstruye nada.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_actualizar_backend.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_actualizar_backend.log
echo ---------------------------------------
echo Abre http://localhost:3000/empresas (deberia verse solo, sin Ctrl+F5 necesario).
pause
exit /b 0

:main
docker-compose restart backend
echo.
echo Esperando...
ping -n 6 127.0.0.1 >nul
docker-compose logs --tail=30 backend
exit /b 0
