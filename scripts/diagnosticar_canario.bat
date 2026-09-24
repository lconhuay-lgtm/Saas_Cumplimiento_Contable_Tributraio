@echo off
cd /d "%~dp0.."

REM Diagnostico de la alerta "El chequeo canario esta fallando" -- pasos
REM 1-3 del playbook (ver PLAYBOOK_FALLOS_SUNAT.md). NO abre navegador, NO
REM entra a SUNAT de nuevo -- solo lee lo que YA quedo guardado:
REM
REM  1. Los ultimos chequeos canario (canario_checks) con su error exacto.
REM  2. Los ultimos errores de consultas normales de clientes (consultas_jobs)
REM     -- para saber si el problema es solo del canario o tambien de
REM     clientes reales.
REM  3. Los logs recientes del scheduler (que es quien corre el canario) --
REM     el traceback completo suele tener mas detalle que el mensaje corto
REM     guardado en la base de datos.
REM  4. La lista de capturas de pantalla/HTML mas recientes en
REM     sunat_data\logs\ -- web_navigation.py ya las genera automaticamente
REM     en cada fallo real contra SUNAT, sin que haga falta correr nada de
REM     nuevo.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_diagnosticar_canario.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_diagnosticar_canario.log
echo ---------------------------------------
echo Comparte ese archivo .log completo -- ahi esta el detalle de cada fallo,
echo si tambien afecto a clientes reales, y los nombres de las capturas de
echo pantalla/HTML que ya se generaron. Si alguna fecha/hora coincide con un
echo fallo, dime el nombre del archivo .html correspondiente en
echo sunat_data\logs\ para leerlo.
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Chequeos canario + errores recientes (base de datos):
echo ---------------------------------------
docker-compose exec -T backend python diagnosticar_canario.py

echo.
echo ---------------------------------------
echo Logs del scheduler (ultimas 200 lineas, para el traceback completo):
echo ---------------------------------------
docker-compose logs --tail=200 scheduler

exit /b 0
