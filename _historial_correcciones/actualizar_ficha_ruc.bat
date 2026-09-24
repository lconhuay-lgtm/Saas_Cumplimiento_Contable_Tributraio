@echo off
cd /d "%~dp0"

REM Aplica los cambios de este round: la Ficha RUC como cuarto boton.
REM  - Backend: nueva migracion 0006 (ficha_ruc_pdf_ref/ficha_ruc_generada_en
REM    en empresas + tabla ficha_ruc_jobs) y endpoints nuevos para
REM    encolar/consultar/descargar la Ficha RUC (usa el mismo adaptador de
REM    Chrome DevTools -> PDF que ya probaste con diagnostico_ficha_ruc.bat).
REM  - Frontend: la grilla de cada tarjeta paso de 3 a 4 casillas (2 filas x
REM    2 columnas, como pediste, para que no se vean apretadas): Pendientes,
REM    Mensajes, Op. en Linea, y ahora Ficha RUC. El boton dice "Generar" la
REM    primera vez (entra en vivo a SUNAT, tarda cerca de un minuto) y "Ver"
REM    las siguientes veces (abre el PDF ya guardado al toque).

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_ficha_ruc.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_ficha_ruc.log
echo ---------------------------------------
echo Abre http://localhost:3000/empresas con Ctrl+F5.
echo.
echo Cosas nuevas para revisar:
echo  1. Cada tarjeta de empresa ahora tiene 4 casillas en 2 filas: Pendientes,
echo     Mensajes, Op. en Linea, y Ficha RUC.
echo  2. Haz clic en "Generar" (Ficha RUC) de cualquier empresa -- va a entrar
echo     en vivo a SUNAT (tarda cerca de un minuto, veras un icono girando).
echo     Al terminar deberia abrirse un visor con el PDF de la Ficha RUC.
echo  3. Cierra el visor y vuelve a hacer clic en el mismo boton -- ahora debe
echo     decir "Ver" y abrir el PDF guardado casi al instante (sin volver a
echo     entrar a SUNAT).
echo  4. Si algo falla, el mensaje de error del intento aparece en una alerta
echo     -- copialo y lo revisamos.
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Corriendo la migracion de base de datos (agrega tablas/columnas de Ficha RUC)...
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
