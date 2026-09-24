@echo off
cd /d "%~dp0"

REM Script de REPARACION para el modulo Cronograma -- corrige 2 problemas
REM reales que aparecieron al probarlo:
REM
REM  1. "column empresas.es_buen_contribuyente does not exist": la
REM     migracion 0011 no llego a aplicarse contra la base de datos real la
REM     vez anterior (probablemente por timing -- el script original le daba
REM     solo unos segundos de margen a que el contenedor recien reconstruido
REM     estuviera listo antes de correr alembic). Este script reintenta el
REM     "alembic upgrade head" varias veces con espera entre intentos, y
REM     ademas verifica con una consulta SQL DIRECTA (no solo confiar en lo
REM     que diga alembic) que la columna realmente haya quedado creada.
REM
REM  2. "No se encontro la tabla del cronograma": el parser buscaba un
REM     <table> HTML, pero la pagina real de SUNAT no arma esa seccion con
REM     un <table> (confirmado con el error real). Se reescribio el parser
REM     para que NO dependa del tipo de markup -- ahora lee el texto plano
REM     de la pagina en el mismo orden en que lo leeria una persona, sin
REM     importar si esta armado con tabla, divs, o lo que sea. Se valido
REM     contra 3 variantes de HTML (con tabla, con divs anidados, y con
REM     parrafos sueltos) reproduciendo los mismos datos reales de SUNAT
REM     2026 -- las 3 variantes dan el resultado correcto ahora.
REM
REM Este script reconstruye la imagen de nuevo (por las dudas de que el
REM build anterior no haya terminado de verdad) y aplica todo de forma mas
REM defensiva, con reintentos y verificacion explicita en cada paso.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_reparar_cronograma.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_reparar_cronograma.log
echo ---------------------------------------
echo.
echo Revisa arriba en la consola (o en el .log) la seccion
echo "VERIFICACION FINAL" -- debe decir:
echo   - "es_buen_contribuyente" encontrada en information_schema (columna SI existe)
echo Si en cambio dice que la columna NO aparece, copiame TODO el contenido
echo de resultado_reparar_cronograma.log para revisar que esta pasando.
echo.
echo Si la verificacion salio bien:
echo  1. Recarga http://localhost:3000/dashboard -- "Actividad reciente" ya
echo     no deberia mostrar el error de columna inexistente.
echo  2. Ve a http://localhost:3000/cronograma y presiona "Sincronizar 2026"
echo     -- ahora deberia funcionar (el parser ya no depende de que la
echo     pagina de SUNAT use una tabla HTML).
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Paso 1/5: Reconstruyendo la imagen (por las dudas de que el build
echo anterior no haya terminado)...
echo ---------------------------------------
docker-compose build backend worker scheduler

echo.
echo ---------------------------------------
echo Paso 2/5: Levantando backend con la imagen nueva...
echo ---------------------------------------
docker-compose up -d --force-recreate backend

echo.
echo ---------------------------------------
echo Paso 3/5: Esperando a que el backend responda de verdad (no un tiempo
echo fijo -- reintenta hasta 6 veces, 5 segundos entre intentos)...
echo ---------------------------------------
set intentos_listo=0
:esperar_backend
set /a intentos_listo+=1
docker-compose exec -T backend python -c "print('listo')" >nul 2>&1
if errorlevel 1 (
    if %intentos_listo% geq 6 (
        echo El backend no respondio tras 6 intentos -- se sigue igual, pero puede fallar el paso siguiente.
        goto fin_espera
    )
    echo Intento %intentos_listo%/6: todavia no responde, esperando...
    ping -n 6 127.0.0.1 >nul
    goto esperar_backend
)
echo El backend ya responde.
:fin_espera

echo.
echo ---------------------------------------
echo Paso 4/5: Migracion de base de datos -- revision ANTES de aplicar:
echo ---------------------------------------
docker-compose exec -T backend alembic current

echo.
echo Corriendo "alembic upgrade head" (hasta 3 intentos)...
set intentos_migracion=0
:intentar_migracion
set /a intentos_migracion+=1
echo.
echo --- Intento %intentos_migracion%/3 ---
docker-compose exec -T backend alembic upgrade head
if errorlevel 1 (
    if %intentos_migracion% lss 3 (
        echo Fallo, esperando 5 segundos y reintentando...
        ping -n 6 127.0.0.1 >nul
        goto intentar_migracion
    )
    echo Se agotaron los 3 intentos -- revisa el error de arriba.
)

echo.
echo Revision DESPUES de aplicar (deberia decir "0011"):
docker-compose exec -T backend alembic current

echo.
echo ---------------------------------------
echo VERIFICACION FINAL: consulta SQL directa contra Postgres (no depende
echo de lo que diga alembic -- confirma la columna de verdad en la base):
echo ---------------------------------------
docker-compose exec -T postgres psql -U buzon -d buzon_saas -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='empresas' AND column_name='es_buen_contribuyente';"
docker-compose exec -T postgres psql -U buzon -d buzon_saas -c "SELECT to_regclass('public.cronograma_vencimientos') AS tabla_cronograma_vencimientos;"

echo.
echo ---------------------------------------
echo Paso 5/5: Reiniciando worker, scheduler y frontend...
echo ---------------------------------------
docker-compose up -d --force-recreate worker scheduler
docker-compose restart frontend

echo.
echo Esperando a que todo termine de levantar...
ping -n 11 127.0.0.1 >nul

echo.
echo ---------------------------------------
echo Logs del backend (ultimas 30 lineas):
echo ---------------------------------------
docker-compose logs --tail=30 backend

exit /b 0
