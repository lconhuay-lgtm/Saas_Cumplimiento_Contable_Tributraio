@echo off
cd /d "%~dp0"

REM No hay dependencias nuevas esta vez (ni pip ni npm), asi que no hace
REM falta reconstruir nada -- el backend recarga solo (--reload) y el
REM frontend tambien (next dev). Solo el worker necesita reiniciarse para
REM levantar el codigo nuevo de clasificacion, porque ese proceso no se
REM autorecarga.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_vista_dividida.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_vista_dividida.log
echo ---------------------------------------
echo Abre http://localhost:3000 (Ctrl+F5) y prueba:
echo  - Empresas: tarjetas mas espaciosas + boton "Consultar todas"
echo  - Click en una empresa: mensajes con pestanas por tipo + PDF al costado
pause
exit /b 0

:main
echo ---------------------------------------
echo Reiniciando el worker (para que tome la clasificacion de mensajes nueva)
echo ---------------------------------------
docker-compose restart worker backend

echo.
echo Esperando a que arranque...
ping -n 8 127.0.0.1 >nul

echo.
echo ---------------------------------------
echo Clasificando por tipo los mensajes que ya estaban guardados
echo ---------------------------------------
set "PYEXE=C:\Users\LCK Business Advisor\AppData\Local\Programs\Python\Python314\python.exe"
"%PYEXE%" -m pip install requests -q
"%PYEXE%" reclasificar_mensajes.py

exit /b 0
