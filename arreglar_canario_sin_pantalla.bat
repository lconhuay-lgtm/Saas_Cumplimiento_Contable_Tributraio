@echo off
cd /d "%~dp0"

REM BUG REAL encontrado con el diagnostico (18/09): la alerta "el chequeo
REM canario esta fallando" NO era un cambio de SUNAT -- el error guardado
REM era "No se pudo iniciar el navegador", que pasa ANTES de intentar
REM siquiera loguearse.
REM
REM Causa: ejecutar_chequeo_canario() abre una sesion de Selenium con
REM headless=False (necesario porque SUNAT corta la conexion si detecta
REM Chrome headless de verdad) -- eso requiere una pantalla virtual (Xvfb).
REM El worker arranca la suya en worker_entry.py, pero el chequeo canario
REM TAMBIEN se llama desde el scheduler (cada 30 min) y desde el backend
REM (boton "Ejecutar chequeo canario ahora") -- ninguno de esos dos procesos
REM arrancaba una pantalla, asi que Chrome nunca podia ni abrir.
REM
REM Arreglo: ejecutar_chequeo_canario() ahora arranca su propia pantalla
REM virtual si detecta que no hay ninguna activa (DISPLAY vacio) -- mismo
REM patron que ya usan los scripts de diagnostico standalone. No hace falta
REM reconstruir la imagen (PyVirtualDisplay ya estaba instalado, se usaba en
REM el worker) -- solo reiniciar.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_arreglar_canario.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_arreglar_canario.log
echo ---------------------------------------
echo Como confirmar que quedo bien:
echo  1. Abre http://localhost:3000/salud
echo  2. Clic en "Ejecutar chequeo canario ahora"
echo  3. Deberia decir "Chequeo corrido: 1 empresa(s) verificada(s)" -- si
echo     antes te salia siempre el mismo error de navegador, ahora deberia
echo     hacer un login real (tarda unos 15-30 segundos) y mostrar el
echo     resultado real (exito o el error real de SUNAT, si lo hay).
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Reiniciando backend, worker y scheduler (sin reconstruir imagen)...
echo ---------------------------------------
docker-compose restart backend worker scheduler

echo.
echo Esperando a que levanten...
ping -n 11 127.0.0.1 >nul

echo.
echo ---------------------------------------
echo Logs del scheduler (ultimas 20 lineas):
echo ---------------------------------------
docker-compose logs --tail=20 scheduler

exit /b 0
