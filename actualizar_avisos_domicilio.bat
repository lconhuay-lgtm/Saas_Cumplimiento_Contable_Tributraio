@echo off
cd /d "%~dp0"

REM Aplica los cambios de este round:
REM  - Backend: bug real corregido -- la condicion de domicilio siempre
REM    daba None porque el selector agarraba una copia oculta (movil) del
REM    elemento en vez de la visible (escritorio).
REM  - Backend: nueva migracion 0005 (condicion_domicilio_anterior +
REM    condicion_domicilio_actualizada_en) para poder avisar de cambios.
REM  - Backend+Frontend: nueva seccion roja en el Dashboard cuando la
REM    condicion de domicilio de una empresa cambia (ej. Habido -> No Habido).
REM  - Frontend: la tarjeta de cada empresa ahora SIEMPRE muestra la
REM    condicion de domicilio (chiquito y neutral si es Habido, aviso rojo
REM    si no lo es).
REM
REM El script de diagnostico_ficha_ruc.py tambien se actualizo (ahora
REM ademas prueba generar un PDF de la Ficha RUC) -- se corre aparte, con
REM diagnostico_ficha_ruc.bat, no hace falta reiniciar nada para eso.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_avisos_domicilio.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_avisos_domicilio.log
echo ---------------------------------------
echo Abre http://localhost:3000/empresas con Ctrl+F5.
echo.
echo Cosas nuevas para revisar:
echo  1. Consulta cualquier empresa de nuevo -- ahora SI deberia guardarse
echo     la condicion de domicilio (antes siempre quedaba vacia por el bug).
echo     En la tarjeta deberia verse "Domicilio fiscal: Habido" chiquito
echo     (o el aviso rojo si no es Habido).
echo  2. Si alguna empresa cambia de condicion entre una consulta y otra,
echo     deberia aparecer una seccion roja arriba del todo en el Dashboard
echo     ("Cambios de domicilio fiscal"). La primera vez que se detecta no
echo     cuenta como cambio, solo las veces siguientes si es distinto.
echo  3. Cuando quieras, corre diagnostico_ficha_ruc.bat de nuevo (aparte,
echo     no hace falta este script) -- ahora tambien intenta generar un PDF
echo     de prueba de la Ficha RUC. Comparte el resultado para confirmar si
echo     funciona antes de conectarlo como boton en la app.
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Corriendo la migracion de base de datos (agrega historial de domicilio)...
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
