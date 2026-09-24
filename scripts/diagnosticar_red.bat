@echo off
cd /d "%~dp0.."

REM Prueba SOLO de red, sin Selenium ni navegador -- compara si el
REM contenedor del worker puede llegar a e-menu.sunat.gob.pe (la que falla)
REM igual que a www.sunat.gob.pe (la que sabemos que funciona). Tarda unos
REM segundos, no gasta ningun intento de login real.

call :main > diagnostico_red.log 2>&1
type diagnostico_red.log

echo.
echo ---------------------------------------
echo Guardado en: %cd%\diagnostico_red.log
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Probando conectividad desde DENTRO del contenedor worker
echo ---------------------------------------
docker-compose exec -T worker python -c "import diag_red"

exit /b 0
