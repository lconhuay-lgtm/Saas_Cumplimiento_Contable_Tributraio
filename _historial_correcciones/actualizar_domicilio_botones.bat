@echo off
cd /d "%~dp0"

REM Aplica los cambios de este round:
REM  - Backend: nueva columna condicion_domicilio en empresas (migracion
REM    Alembic 0004) + deteccion real (Habido/No Habido/No Hallado) en cada
REM    consulta, confirmado con HTML real de produccion.
REM  - Frontend: nota roja en la tarjeta si el domicilio NO es "Habido".
REM  - Frontend: el boton "Operaciones en Linea" ahora es del mismo tamaño
REM    que "Pendientes" y "Mensajes" (3 casillas repartidas por igual).
REM
REM No se agrego ninguna dependencia nueva de npm, pero SI hay una
REM migracion de base de datos nueva -- hay que correr alembic.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_domicilio_botones.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_domicilio_botones.log
echo ---------------------------------------
echo Abre http://localhost:3000/empresas con Ctrl+F5.
echo.
echo Cosas nuevas para revisar:
echo  1. Las 3 casillas de cada tarjeta (Pendientes, Mensajes, Op. en Linea)
echo     ahora deben verse del mismo tamaño, repartidas en 3 columnas iguales.
echo  2. Consulta una empresa que sepas que tiene "No Habido" o "No Hallado"
echo     en su domicilio fiscal (si no tienes ninguna a mano, no hay como
echo     verlo hasta que aparezca una asi) -- deberia verse una nota roja
echo     arriba de las 3 casillas, debajo del nombre de la empresa.
echo  3. Si quieres ayudarme a investigar lo de "baja de oficio" (estado
echo     del contribuyente), corre por separado: diagnostico_ficha_ruc.bat
echo     (lee sus instrucciones, no hace falta correrlo ahora).
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Corriendo la migracion de base de datos (agrega condicion_domicilio)...
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
