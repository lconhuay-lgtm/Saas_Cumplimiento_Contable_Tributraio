@echo off
cd /d "%~dp0.."

REM Corre el diagnostico de "Ver Ficha Ruc" DENTRO del contenedor worker (ya
REM tiene Chrome, Selenium y la base de datos accesibles). Usa una empresa
REM que ya tengas guardada en el sistema -- no pide credenciales nuevas.
REM
REM Uso:
REM   diagnostico_ficha_ruc.bat            -> usa la primera empresa con
REM                                            credenciales que encuentre
REM   diagnostico_ficha_ruc.bat 20494056934 -> usa esa empresa puntual
REM
REM Esto SI entra a SUNAT de verdad (como una consulta normal), pero no
REM descarga mensajes ni cambia nada -- solo mira la Ficha RUC.

if "%~1"=="_run" goto main

set "RUC_PARAM=%~1"

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run \"%RUC_PARAM%\"' } 2>&1 | Tee-Object -FilePath 'resultado_diagnostico_ficha_ruc.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_diagnostico_ficha_ruc.log
echo ---------------------------------------
echo Los archivos de evidencia (HTML + captura) quedaron en la carpeta
echo sunat_data\logs\ con el nombre "diagnostico_ficha_ruc_...".
echo Comparte el .html (o dime el nombre del archivo) para que pueda leerlo
echo y confirmar si el "estado del contribuyente" (baja de oficio) esta ahi.
echo ---------------------------------------
pause
exit /b 0

:main
set "RUC_ARG=%~2"
echo ---------------------------------------
echo Corriendo diagnostico dentro del worker...
echo ---------------------------------------
if "%RUC_ARG%"=="" (
    docker-compose exec -T worker python diagnostico_ficha_ruc.py
) else (
    docker-compose exec -T worker python diagnostico_ficha_ruc.py %RUC_ARG%
)
exit /b 0
