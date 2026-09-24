@echo off
cd /d "%~dp0"

REM Aplica los cambios de este round:
REM  - Tipografia Dosis (titulos) + Open Sans (texto), igual a novodivisas.com
REM  - Colores por tipo de mensaje en las etiquetas (Orden de Pago, Coactiva, etc.)
REM  - El numero de "Consultas" ya no aparece destacado, ahora esta chiquito
REM  - Backend: al hacer una consulta, se lee el nombre real que SUNAT
REM    reconoce para el RUC (banner "Bienvenido, ...") y se corrige la
REM    razon social guardada si difiere de la que trae el Excel/formulario.
REM
REM Esto ultimo corre en el WORKER (ahi es donde se ejecuta el scraping), asi
REM que hay que reiniciar backend, worker Y frontend. No se agrego ninguna
REM dependencia nueva de npm, asi que no hace falta --force-recreate ni -V.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_estilos_razonsocial.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_estilos_razonsocial.log
echo ---------------------------------------
echo Abre http://localhost:3000/empresas con Ctrl+F5 (para forzar recarga).
echo.
echo Cosas nuevas para revisar:
echo  1. Los titulos (Dashboard, Empresas, nombres de empresa) deberian verse
echo     con una tipografia mas redondeada/elegante (Dosis).
echo  2. En "Ultimo mensaje" de cada tarjeta, la etiqueta del tipo debe tener
echo     color segun que es: rojo=Orden de Pago, rosado=Coactiva, naranja=Multa,
echo     morado=Intendencia, etc.
echo  3. Ya no se ve un tercer recuadro de "Consultas" en las tarjetas -- ahora
echo     son 2 recuadros (Pendientes, Mensajes) y el numero de consultas esta
echo     chiquito abajo, junto a la fecha de la ultima consulta.
echo  4. Para probar lo de la razon social: haz clic en "Consultar" en una
echo     empresa cuyo nombre en el sistema NO coincida exactamente con el que
echo     SUNAT le reconoce (o cambia a mano el nombre de una empresa de prueba
echo     para que quede distinto, y luego consultala) -- despues de la
echo     consulta el nombre deberia corregirse solo. Revisa tambien los logs
echo     del worker: deberia aparecer una linea
echo     "Actualizando razon social de <RUC> segun SUNAT: '...' -^> '...'"
echo     si el nombre cambio.
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Reiniciando backend, worker y frontend
echo ---------------------------------------
docker-compose restart backend worker frontend

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
echo Logs del worker (ultimas 15 lineas):
echo ---------------------------------------
docker-compose logs --tail=15 worker

echo.
echo ---------------------------------------
echo Logs del frontend (debe decir "Ready"):
echo ---------------------------------------
docker-compose logs --tail=30 frontend

exit /b 0
