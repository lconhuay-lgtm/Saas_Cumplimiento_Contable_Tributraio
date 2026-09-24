@echo off
cd /d "%~dp0"

REM Nuevo modulo: "Cronograma" -- agenda de vencimientos de declaracion
REM mensual (IGV-Renta/PDT.621 y PLAME/F.601) segun el cronograma OFICIAL
REM de SUNAT (Resolucion de Superintendencia 281-2022, vigente de forma
REM permanente desde 2023).
REM
REM Como funciona:
REM  - Backend: nuevo modulo app/cronograma_sunat.py descarga y parsea la
REM    pagina publica y estatica de SUNAT
REM    (sunat.gob.pe/orientacion/cronogramas/{anio}/cObligacionMensual{anio}.html)
REM    -- a diferencia de todo lo demas que se scrapea de SUNAT, esta pagina
REM    NO requiere sesion ni Selenium, es un simple GET + parseo de HTML.
REM  - Cada empresa se cruza contra el cronograma por el ULTIMO DIGITO de su
REM    RUC (o por la fecha extendida de "Buenos Contribuyentes/UESP" si se
REM    marca asi en su detalle) para saber cuando le toca declarar.
REM  - La sincronizacion es automatica: se dispara sola al arrancar el
REM    backend y una vez al dia desde el scheduler (05:00 UTC) -- no hace
REM    falta tocar nada a mano. Tambien hay un boton "Sincronizar" manual
REM    en la pagina, por si SUNAT publica una modificacion (p.ej. una
REM    prorroga) y no se quiere esperar al chequeo diario.
REM  - Nueva migracion 0011: agrega empresas.es_buen_contribuyente y la
REM    tabla cronograma_vencimientos.
REM  - Nuevos endpoints: POST /cronograma/sincronizar, GET
REM    /cronograma/agenda, GET /cronograma/proximos.
REM  - Frontend: pagina nueva /cronograma (calendario mes a mes, clickeable
REM    por dia), enlace "Cronograma" en el menu de la izquierda, seccion
REM    "Proximos vencimientos" en el Dashboard, y boton "Marcar Buen
REM    Contribuyente" en el detalle de cada empresa.
REM
REM IMPORTANTE: este modulo agrega 2 paquetes Python nuevos (requests,
REM beautifulsoup4) a requirements.txt -- a diferencia de otras
REM actualizaciones anteriores, esta vez hace falta RECONSTRUIR la imagen
REM (docker-compose build), no alcanza con reiniciar.
REM
REM Todo esto se probo con pruebas automatizadas (parser contra los datos
REM reales de SUNAT 2026, mas fakeredis + SQLite + FastAPI TestClient de
REM punta a punta: crear empresas, sincronizar, ver agenda por mes, ver
REM proximos vencimientos, marcar Buen Contribuyente) -- lo que falta es la
REM prueba real en tu maquina, que es lo que este script prepara.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_cronograma_sunat.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_cronograma_sunat.log
echo ---------------------------------------
echo.
echo Como probarlo:
echo  1. Abre http://localhost:3000/cronograma (o el enlace "Cronograma"
echo     en el menu de la izquierda, entre "Empresas" y "Salud del sistema").
echo  2. Deberia verse un calendario del mes actual. Si al backend le costo
echo     alcanzar sunat.gob.pe al arrancar (o es la primera vez), puede que
echo     el calendario aparezca vacio -- en ese caso presiona el boton
echo     "Sincronizar 2026" (arriba a la derecha) y espera unos segundos.
echo  3. Los dias con vencimientos muestran una etiqueta azul con la
echo     cantidad de empresas. Haz clic en un dia asi para ver el detalle:
echo     que empresa vence ese dia y con que periodo tributario.
echo  4. Ve a http://localhost:3000/dashboard -- si alguna empresa tiene un
echo     vencimiento dentro de los proximos 15 dias, deberia aparecer una
echo     seccion ambar "Proximos vencimientos" arriba de las tarjetas.
echo  5. Entra al detalle de una empresa (clic en su nombre desde la lista)
echo     -- deberia verse un boton nuevo "Marcar Buen Contribuyente" junto
echo     al de "Marcar como cuenta canario". Al activarlo, esa empresa pasa
echo     a usar la fecha extendida de "Buenos Contribuyentes y UESP" en vez
echo     del cronograma general por ultimo digito de RUC.
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Reconstruyendo la imagen de backend/worker/scheduler (nuevos paquetes:
echo requests, beautifulsoup4)...
echo ---------------------------------------
docker-compose build backend worker scheduler

echo.
echo ---------------------------------------
echo Corriendo la migracion de base de datos (agrega es_buen_contribuyente
echo + tabla cronograma_vencimientos)...
echo ---------------------------------------
docker-compose up -d backend
ping -n 6 127.0.0.1 >nul
docker-compose exec -T backend alembic upgrade head

echo.
echo ---------------------------------------
echo Reiniciando backend, worker, scheduler y frontend...
echo ---------------------------------------
docker-compose up -d backend worker scheduler frontend
docker-compose restart backend worker scheduler frontend

echo.
echo Esperando a que levanten (el backend intenta sincronizar el cronograma
echo del anio actual apenas arranca)...
ping -n 16 127.0.0.1 >nul

echo.
echo ---------------------------------------
echo Logs del backend (ultimas 30 lineas -- busca "Cronograma SUNAT
echo sincronizado al arrancar" o el aviso de que no se pudo):
echo ---------------------------------------
docker-compose logs --tail=30 backend

echo.
echo ---------------------------------------
echo Logs del scheduler (deberia mencionar "Verificacion del cronograma
echo SUNAT a las 05:00 UTC"):
echo ---------------------------------------
docker-compose logs --tail=20 scheduler

echo.
echo ---------------------------------------
echo Logs del frontend (debe decir "Ready"):
echo ---------------------------------------
docker-compose logs --tail=20 frontend

exit /b 0
