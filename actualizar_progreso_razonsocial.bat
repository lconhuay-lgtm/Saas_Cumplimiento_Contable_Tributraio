@echo off
cd /d "%~dp0"

REM Aplica los cambios de este round:
REM  - Backend: 2 bugs reales de razon social corregidos (con evidencia de
REM    tus logs de hoy): se ignoran los recortes falsos del banner de SUNAT,
REM    y ya no se pierde el nombre detectado si el resto de la consulta falla.
REM  - Backend: chequeo automatico ahora corre DOS veces al dia (11:00 y
REM    19:30 hora Peru) en vez de una sola vez de madrugada.
REM  - Backend+Frontend: nuevo endpoint /consultas/estado + boton "Consultar
REM    todas" deshabilitado mientras hay una tanda en curso, con una "nube"
REM    de progreso al pasar el mouse (se actualiza sola, y tambien detecta
REM    las tandas que dispare el chequeo automatico).
REM  - Frontend: boton "Operaciones en Linea" en cada tarjeta de empresa
REM    (nunca pasa tu clave SOL, solo abre el Menu SOL real de SUNAT).
REM
REM No se agrego ninguna dependencia nueva de npm, asi que no hace falta
REM --force-recreate ni -V, solo reiniciar los contenedores.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_progreso_razonsocial.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_progreso_razonsocial.log
echo ---------------------------------------
echo Abre http://localhost:3000/empresas con Ctrl+F5.
echo.
echo Cosas nuevas para revisar:
echo  1. Boton "Consultar todas": haz clic, y mientras este trabajando
echo     pasale el mouse por encima -- debe aparecer una "nube" con el
echo     avance (X/Y completadas) y el boton debe verse deshabilitado
echo     (no clickeable) hasta que termine.
echo  2. En cada tarjeta de empresa, abajo, deberia verse un boton verde
echo     "Operaciones en Linea" al lado de "Consultar". Haz clic: te lleva
echo     al Menu SOL real de SUNAT en una pestaña nueva. Si ya tenias
echo     sesion abierta en SUNAT en ESE MISMO navegador, entras directo
echo     sin volver a loguearte -- si no, te pide usuario/clave como
echo     siempre (nunca pasamos tu clave por nuestra app).
echo  3. Razon social: si tienes alguna empresa con el nombre mal escrito,
echo     consultala de nuevo y revisa si se corrigio. Si quieres que
echo     revise algo puntual, dime el RUC y te ayudo a leer los logs.
echo  4. El chequeo automatico ahora es 2 veces al dia. Revisa los logs
echo     del scheduler (abajo) -- debe decir algo como "Chequeos diarios
echo     a las 16:00 UTC (11:00 Peru) y 00:30 UTC (19:30 Peru)".
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Reiniciando backend, worker, scheduler y frontend
echo ---------------------------------------
docker-compose restart backend worker scheduler frontend

echo.
echo Esperando a que levanten...
ping -n 11 127.0.0.1 >nul

echo.
echo ---------------------------------------
echo Logs del backend (ultimas 15 lineas):
echo ---------------------------------------
docker-compose logs --tail=15 backend

echo.
echo ---------------------------------------
echo Logs del scheduler (debe mostrar los nuevos horarios):
echo ---------------------------------------
docker-compose logs --tail=15 scheduler

echo.
echo ---------------------------------------
echo Logs del frontend (debe decir "Ready"):
echo ---------------------------------------
docker-compose logs --tail=30 frontend

exit /b 0
