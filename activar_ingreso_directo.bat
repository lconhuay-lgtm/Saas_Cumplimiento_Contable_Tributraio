@echo off
cd /d "%~dp0"

REM Nueva funcionalidad: "Ingreso Directo a SUNAT". Boton en la pantalla de
REM una empresa que abre una pestana nueva YA logueada en Operaciones en
REM Linea de SUNAT, sin escribir nada -- inspirado en revisar como lo hace
REM un competidor, pero implementado desde cero contra el mecanismo real de
REM login de SUNAT (formulario j_security_check, confirmado con el codigo
REM fuente real de la pagina de login).
REM
REM Como funciona (por si algo sale raro y hay que revisar logs):
REM  1. El navegador pide un token de un solo uso (dura 2 minutos).
REM  2. Se abre una pestana nueva apuntando a un endpoint del backend con
REM     ese token.
REM  3. El backend hace un login de prueba con Selenium SOLO hasta la
REM     pantalla de login (sin escribir usuario/clave todavia) para
REM     conseguir los datos frescos que pide SUNAT en ese momento (state,
REM     originalUrl). Esto tarda 15-30 segundos.
REM  4. El backend devuelve una pagina HTML con un formulario oculto,
REM     precargado con el RUC/usuario/clave de la empresa (descifrados en el
REM     servidor) y esos datos frescos, que se autoenvia con JavaScript.
REM  5. Ese envio lo hace el NAVEGADOR REAL del usuario (no Selenium) --
REM     por eso la sesion de SUNAT que resulta queda en la pestana del
REM     usuario, lista para usar Operaciones en Linea.
REM
REM No hace falta reconstruir ninguna imagen Docker -- backend, worker,
REM scheduler y frontend montan el codigo en vivo (bind mounts) y el
REM frontend corre en modo desarrollo (next dev), asi que un simple reinicio
REM alcanza para que tomen el codigo nuevo.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_ingreso_directo.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_ingreso_directo.log
echo ---------------------------------------
echo Como probarlo (con una empresa que ya tenga usuario y clave SOL
echo guardados -- si no tenes ninguna real a mano, se puede probar con
echo cualquier empresa que tenga credenciales cargadas, aunque el login
echo final falle, para ver que la pestana y el flujo se abren bien):
echo  1. Abre http://localhost:3000/empresas
echo  2. En la TARJETA de la empresa (lista, NO hace falta entrar al buzon)
echo     busca la casilla verde "Ir / Op. en Linea" -- es la que antes
echo     abria el portal de SUNAT sin loguear, ahora hace login automatico
echo  3. Clic en esa casilla (NO en el iconito chiquito de la esquina, ese
echo     es el enlace manual de respaldo)
echo  4. Se abre una pestana nueva que dice "Entrando a SUNAT..." o similar
echo     mientras carga (15-30 segundos es normal, esta haciendo un login
echo     de prueba con Selenium de fondo)
echo  5. Si todo sale bien, esa pestana termina mostrando Operaciones en
echo     Linea de SUNAT ya logueado, sin haber escrito nada
echo  6. Si algo sale mal, la pestana muestra una pagina de error con el
echo     motivo (por ejemplo: "no se pudo llegar a la pantalla de login",
echo     credenciales incorrectas, etc.) -- copiame ese mensaje si pasa
echo ---------------------------------------
echo Si la pestana no llega a abrirse (el navegador bloqueo el popup):
echo  - Revisa el icono de "popup bloqueado" en la barra de direcciones
echo    y permite popups para localhost:3000
echo ---------------------------------------
echo Nota: el boton NO esta dentro del buzon de la empresa (esa pantalla
echo de mensajes se dejo como estaba) -- vive en la tarjeta de la lista,
echo en el mismo lugar donde ya estaba el enlace a Operaciones en Linea.
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Reiniciando backend, worker, scheduler y frontend (sin reconstruir imagen)...
echo ---------------------------------------
docker-compose restart backend worker scheduler frontend

echo.
echo Esperando a que levanten...
ping -n 11 127.0.0.1 >nul

echo.
echo ---------------------------------------
echo Logs del backend (ultimas 30 lineas, deberia arrancar sin errores):
echo ---------------------------------------
docker-compose logs --tail=30 backend

echo.
echo ---------------------------------------
echo Logs del frontend (ultimas 20 lineas, deberia decir "compiled" o similar):
echo ---------------------------------------
docker-compose logs --tail=20 frontend

exit /b 0
