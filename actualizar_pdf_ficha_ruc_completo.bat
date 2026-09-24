@echo off
cd /d "%~dp0"

REM Corrige el PDF de la Ficha RUC: confirmado con el diagnostico que
REM compartiste (v1_ANTES_del_clic.pdf vs v2_DESPUES_del_clic.pdf) que la
REM produccion estaba generando la pantalla intermedia "Datos de Ficha RUC
REM - Modificacion..." (con los botones de edicion alrededor) en vez de la
REM "CIR - Constancia de Informacion Registrada" real. Ahora el adaptador
REM hace clic en el boton interno "Ficha RUC" (el que marcaste en la
REM captura) antes de generar el PDF -- el resultado incluye domicilio
REM fiscal detallado, documento de identidad y tributos afectos que antes
REM no salian.
REM
REM No hace falta migracion de base de datos para esto -- solo reiniciar
REM el worker (que es quien corre el scraping) para que tome el cambio.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_pdf_ficha_ruc_completo.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_pdf_ficha_ruc_completo.log
echo ---------------------------------------
echo Abre http://localhost:3000/empresas con Ctrl+F5.
echo.
echo Para confirmar que quedo bien:
echo  1. En cualquier empresa que ya tenga una Ficha RUC generada, haz clic
echo     en el iconito de refrescar (arriba a la derecha del boton) para
echo     forzar una version nueva.
echo  2. El PDF que se abre ahora deberia decir "CIR - Constancia de
echo     Informacion Registrada" y un "Numero de Transaccion" arriba, y mas
echo     abajo deberia traer el domicilio fiscal completo (departamento,
echo     provincia, distrito, direccion) y el documento de identidad -- eso
echo     es lo que NO salia antes.
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
echo Logs del worker (ultimas 15 lineas):
echo ---------------------------------------
docker-compose logs --tail=15 worker

exit /b 0
