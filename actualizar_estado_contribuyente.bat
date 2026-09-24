@echo off
cd /d "%~dp0"

REM Aplica el ultimo cambio de este round: captura del "Estado del
REM Contribuyente" (Activo / Baja de Oficio / etc.) en TODAS las consultas
REM (incluido el chequeo automatico de las 11am/7:30pm), confirmado que no
REM se puede leer del banner normal -- entra brevemente a la Ficha RUC
REM (sin generar PDF, solo texto, ~8-10 segundos extra por empresa).
REM
REM Este script ya incluye el reinicio completo, asi que TAMBIEN aplica el
REM arreglo del PDF de Ficha RUC (boton interno) de
REM actualizar_pdf_ficha_ruc_completo.bat -- si ya corriste ese no pasa
REM nada, este simplemente reinicia todo de nuevo.
REM
REM Cambios incluidos:
REM  - Nueva migracion 0008 (estado_contribuyente + anterior + fecha en
REM    empresas).
REM  - core_scraper/web_navigation.py: nuevo metodo
REM    _leer_estado_contribuyente() (entra a la Ficha RUC, lee el texto,
REM    vuelve).
REM  - core_scraper/adapter.py: consultar_buzon() ahora tambien captura el
REM    estado del contribuyente en cada consulta.
REM  - Backend: se guarda estado_contribuyente + estado_contribuyente_anterior
REM    (mismo patron que la condicion de domicilio -- la primera deteccion
REM    no cuenta como "cambio").
REM  - Frontend: la tarjeta de cada empresa muestra el estado del
REM    contribuyente (aviso rojo si no es "Activo"), y el Dashboard avisa
REM    cuando cambia, igual que con el domicilio fiscal.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_estado_contribuyente.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_estado_contribuyente.log
echo ---------------------------------------
echo Abre http://localhost:3000/empresas con Ctrl+F5.
echo.
echo Cosas nuevas para revisar:
echo  1. Consulta cualquier empresa de nuevo (manual o espera al chequeo
echo     automatico) -- ahora deberia tardar unos 8-10 segundos mas
echo     (entra brevemente a la Ficha RUC para leer el estado).
echo  2. En la tarjeta deberia verse "Estado del contribuyente: Activo"
echo     chiquito (o el aviso rojo si no es Activo), arriba de la linea de
echo     domicilio fiscal.
echo  3. Si el estado de alguna empresa cambia entre una consulta y otra,
echo     deberia aparecer una seccion roja arriba del todo en el Dashboard
echo     ("Cambios de estado del contribuyente"). La primera vez que se
echo     detecta no cuenta como cambio, solo las veces siguientes si es
echo     distinto.
echo  4. De paso, prueba de nuevo generar (o regenerar) una Ficha RUC -- el
echo     PDF ya deberia ser la version completa (con domicilio fiscal
echo     detallado y documento de identidad), no la pantalla de edicion de
echo     antes.
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Corriendo la migracion de base de datos (agrega estado_contribuyente)...
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
