@echo off
cd /d "%~dp0"

REM Aplica los cambios de este round:
REM  - Backend: nueva migracion 0007 (columna "etapa" en ficha_ruc_jobs) +
REM    el adaptador ahora reporta el avance real (iniciando sesion,
REM    autenticando, abriendo la ficha, generando el PDF, guardando).
REM  - Frontend: el boton de Ficha RUC ahora muestra una barra de progreso
REM    con el % y la etapa mientras se genera (en vez de un spinner sin
REM    contexto), y un icono de "generar de nuevo" + la fecha de la ultima
REM    generacion cuando ya existe una (para saber si puede estar
REM    desactualizada). "Ver" abre la version guardada al toque; "generar
REM    de nuevo" siempre entra en vivo a SUNAT.
REM
REM El script de diagnostico_ficha_ruc.py TAMBIEN se actualizo (aparte, con
REM diagnostico_ficha_ruc.bat) para investigar dos cosas pendientes:
REM  1. El PDF que se genera hoy resulto ser la pantalla intermedia
REM     "Datos de Ficha RUC - Modificacion..." en vez de la ficha completa
REM     -- el script ahora prueba hacer clic en el boton interno "Ficha
REM     RUC" (el que marcaste en la captura) antes de generar el PDF.
REM  2. Si el "Estado del Contribuyente" (Activo/Baja de oficio) se puede
REM     leer gratis en el banner normal del Menu SOL, o si de verdad solo
REM     aparece dentro de la Ficha RUC.
REM Corre diagnostico_ficha_ruc.bat aparte (no hace falta reiniciar nada
REM para eso) y comparte los archivos que indique al final, sobre todo los
REM que digan "06_pestana_DESPUES_del_clic" y "v2_DESPUES_del_clic".

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_progreso_ficha_ruc.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_progreso_ficha_ruc.log
echo ---------------------------------------
echo Abre http://localhost:3000/empresas con Ctrl+F5.
echo.
echo Cosas nuevas para revisar:
echo  1. Genera una Ficha RUC de alguna empresa -- ahora deberias ver un %%
echo     y una etiqueta ("Iniciando sesion...", "Generando el PDF...", etc.)
echo     junto con una barrita que avanza, en vez de solo un icono girando.
echo  2. Una vez generada, la tarjeta muestra "hace X min/h" debajo del
echo     boton, y aparece un icono chiquito de refrescar en la esquina --
echo     haz clic ahi para forzar una version nueva sin cerrar/abrir nada.
echo  3. Dentro del visor de la Ficha RUC tambien hay un boton "Generar de
echo     nuevo" junto a la fecha de generacion.
echo  4. Cuando puedas, corre diagnostico_ficha_ruc.bat aparte (no requiere
echo     reiniciar nada) para seguir investigando el PDF incompleto y el
echo     estado del contribuyente -- comparte los archivos que te indique
echo     al final para poder terminar de corregir eso.
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Corriendo la migracion de base de datos (agrega columna "etapa")...
echo ---------------------------------------
docker-compose exec -T backend alembic upgrade head

echo.
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
echo Logs del frontend (debe decir "Ready"):
echo ---------------------------------------
docker-compose logs --tail=30 frontend

exit /b 0
