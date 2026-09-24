@echo off
cd /d "%~dp0"

REM Mide cuanto tiempo sigue siendo valido un ticket de "ingreso directo"
REM (los datos que SUNAT genera para el login: state/originalUrl) despues
REM de generado, antes de que SUNAT lo rechace. Hace VARIOS logins reales
REM seguidos con una empresa que ya tengas guardada (por defecto la cuenta
REM canario, si tenes una marcada) -- no escribe nada distinto a un login
REM normal, solo mide en que momento deja de funcionar un ticket viejo.
REM
REM Para que sirve: el boton "Ir a SUNAT" ahora intenta usar un ticket
REM "pre-calentado" en cache (ver ARREGLAR_INGRESO_DIRECTO_MAS_RAPIDO mas
REM abajo) para responder casi al instante en vez de tardar 15-30 segundos
REM -- pero por seguridad el cache descarta ese ticket si tiene mas de 45
REM segundos, un numero elegido a ojo porque todavia no se habia medido el
REM limite real de SUNAT. Este script mide ese limite real.
REM
REM Tarda 8-10 minutos en total (6 rondas, cada una espera un poco mas que
REM la anterior antes de usar el ticket -- mantiene la MISMA pestaña de
REM Chrome abierta durante toda la espera y recien ahi envia el formulario,
REM para que el delay sea la unica variable que cambia entre rondas).

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_frescura_ingreso_directo.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_frescura_ingreso_directo.log
echo ---------------------------------------
echo Al final del log hay un RESUMEN con cada delay probado (0/20/40/60/90/120
echo segundos) y si SUNAT lo acepto o lo rechazo. Compartime ese resumen --
echo con eso ajusto DEFAULT_MAX_EDAD_SEG en backend/app/ingreso_directo_cache.py
echo para que el cache aproveche toda la ventana real que SUNAT permite (hoy
echo esta en 45s, conservador a proposito hasta tener este dato).
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Corriendo el diagnostico de frescura (va a tardar varios minutos, no cierres esta ventana)...
echo ---------------------------------------
docker-compose exec -T worker python diagnosticar_frescura_ingreso_directo.py

exit /b 0
