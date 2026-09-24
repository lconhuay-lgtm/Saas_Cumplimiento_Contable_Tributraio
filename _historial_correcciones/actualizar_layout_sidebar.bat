@echo off
cd /d "%~dp0"

REM Aplica los cambios de este round: backend (ultimo_mensaje en EmpresaResponse)
REM y frontend (sidebar izquierdo, tarjetas de 2 columnas con ultimo mensaje y
REM PDF rapido, visor de PDF mas grande, filtros por URL, boton "volver" visible).
REM No se agrego ninguna dependencia nueva de npm, asi que no hace falta
REM --force-recreate ni -V, solo reiniciar los contenedores.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_layout_sidebar.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_layout_sidebar.log
echo ---------------------------------------
echo Abre http://localhost:3000/dashboard con Ctrl+F5 (para forzar recarga).
echo.
echo Cosas nuevas para revisar:
echo  1. Menu lateral oscuro a la izquierda (Dashboard/Empresas) con tu
echo     email abajo y boton de cerrar sesion.
echo  2. En Empresas: tarjetas de a 2 por fila, con el ultimo mensaje y su
echo     tipo (Orden de Pago, etc.), boton "Ver PDF" si tiene documento.
echo  3. Las etiquetas "Pendientes" y "X hoy" de cada tarjeta ahora llevan
echo     directo al buzon de esa empresa con ese filtro ya aplicado.
echo  4. Dentro del buzon de una empresa: el visor de PDF es mas grande, y
echo     el boton "Volver a empresas" ahora se ve como un boton de verdad.
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Reiniciando backend y frontend
echo ---------------------------------------
docker-compose restart backend frontend

echo.
echo Esperando a que levanten...
ping -n 11 127.0.0.1 >nul

echo.
echo ---------------------------------------
echo Logs del backend (ultimas 20 lineas):
echo ---------------------------------------
docker-compose logs --tail=20 backend

echo.
echo ---------------------------------------
echo Logs del frontend (debe decir "Ready"):
echo ---------------------------------------
docker-compose logs --tail=30 frontend

exit /b 0
