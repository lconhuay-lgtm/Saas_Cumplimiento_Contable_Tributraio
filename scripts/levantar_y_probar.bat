@echo off
cd /d "%~dp0.."

echo ---------------------------------------
echo Fase 0 - Levantando el stack (Postgres + backend FastAPI)
echo ---------------------------------------

if not exist ".env" (
    echo Copiando .env.example a .env ...
    copy /Y .env.example .env
)

echo.
echo Construyendo y levantando contenedores...
docker-compose up -d --build
if errorlevel 1 (
    echo.
    echo ERROR: docker-compose fallo. Verifica que Docker Desktop este abierto y corriendo.
    pause
    exit /b 1
)

echo.
echo Esperando a que Postgres y el backend esten listos...
timeout /t 12 /nobreak

echo.
echo Corriendo migraciones de base de datos...
docker-compose exec -T backend alembic upgrade head

echo.
echo ---------------------------------------
echo Probando la API end-to-end
echo ---------------------------------------
set "PYEXE=C:\Users\LCK Business Advisor\AppData\Local\Programs\Python\Python314\python.exe"
"%PYEXE%" -m pip install requests -q
"%PYEXE%" "%~dp0probar_api.py"

echo.
echo ---------------------------------------
echo Logs del backend (ultimas 40 lineas, por si algo fallo):
echo ---------------------------------------
docker-compose logs --tail=40 backend

echo.
echo Listo. La API queda corriendo en http://localhost:8000/docs
pause
