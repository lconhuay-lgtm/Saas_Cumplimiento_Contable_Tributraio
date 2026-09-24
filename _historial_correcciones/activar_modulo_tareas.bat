@echo off
cd /d "%~dp0"

REM Nuevo modulo: "Tareas" -- agenda de obligaciones configurables por
REM empresa (Planilla, AFP, Reportes SBS, u otras a medida), ademas de las
REM 3 correcciones reales del modulo Cronograma que ya se habian entregado:
REM
REM  1. Filtro: las empresas inactivas o con "Baja de Oficio/Provisional/
REM     Definitiva" ya NO aparecen en el cronograma ni en "Proximos
REM     vencimientos". Las que estan "No Habido"/"No Hallado" SI siguen
REM     apareciendo (siguen siendo contribuyentes activos).
REM  2. Parser del cronograma SUNAT corregido -- ya no depende de que la
REM     pagina use una tabla HTML.
REM  3. Migracion de la columna es_buen_contribuyente reforzada.
REM
REM Modulo de Tareas (nuevo):
REM  - Por cada empresa, en su pantalla de detalle, hay una seccion
REM    "Obligaciones de esta empresa" para marcar cuales le corresponden:
REM    Planilla, AFP, Reporte SBS, u Otro -- no todas las empresas tienen
REM    todas. Cada obligacion elige su regla de vencimiento:
REM      - "Cronograma SUNAT": Planilla y AFP se declaran junto con la
REM        PLAME, asi que comparten la MISMA fecha que ya calcula el
REM        modulo Cronograma por ultimo digito de RUC -- confirmado
REM        investigando como funciona la PLAME en Peru.
REM      - "Dia fijo del mes": vence un dia fijo cada mes.
REM      - "Manual": sin regla automatica (para Reportes SBS, cuyo plazo
REM        varia mucho segun el tipo de reporte y no sigue un cronograma
REM        fijo) -- la fecha se carga a mano cada vez.
REM  - Nueva pagina "Tareas" en el menu: lista de tareas pendientes con
REM    prioridad y vencimiento, filtros por estado, boton "Generar tareas
REM    del mes" (idempotente, se puede apretar las veces que haga falta),
REM    y boton para crear tareas sueltas a mano (ej. "Responder esquela
REM    de SUNAT").
REM
REM Rediseno visual (Dashboard + Calendario), inspirado en el competidor:
REM  - Dashboard: las 4 tarjetas de metricas ahora son de color solido
REM    (verde/ambar/rosa/teal) con icono en circulo, igual de estilo al
REM    del competidor -- Notificaciones nuevas, Eventos, Tareas pendientes
REM    y Ultima sincronizacion. Debajo se agrego el panel "Avance de
REM    Cumplimiento": una tarjeta por tipo de obligacion (Planilla/AFP/
REM    Reporte SBS/Otro) con Total, Completados y una barra de progreso,
REM    mas un selector de periodo tributario (ultimos 12 meses). Si no
REM    hay obligaciones configuradas todavia, muestra un mensaje
REM    explicando donde configurarlas.
REM  - Calendario (Cronograma): cada dia del mes ahora muestra hasta 3
REM    "chips" con el nombre de cada empresa que vence ese dia (coloreados
REM    por grupo de RUC), en vez de solo un numero -- y un "+N mas" si hay
REM    mas de 3. El panel de detalle del dia (al hacer clic) tambien usa
REM    esos mismos colores por grupo.
REM
REM Todo esto se probo con pruebas automatizadas (fakeredis + SQLite +
REM FastAPI TestClient de punta a punta: configurar obligaciones, generar
REM tareas, verificar que Planilla y AFP comparten fecha, marcar
REM completado, filtros, tareas manuales -- 27 verificaciones, todas
REM correctas) y el codigo nuevo del frontend se valido con un parser de
REM JS/JSX (sin errores de sintaxis). Lo que falta es la prueba visual
REM real en tu navegador.

if "%~1"=="_run" goto main

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { cmd /c '\"%~f0\" _run' } 2>&1 | Tee-Object -FilePath 'resultado_modulo_tareas.log'"

echo.
echo ---------------------------------------
echo Resultado guardado en: %cd%\resultado_modulo_tareas.log
echo ---------------------------------------
echo.
echo Revisa la seccion "VERIFICACION FINAL" -- debe confirmar que las
echo tablas empresa_obligaciones y tarea_obligaciones existen.
echo.
echo Como probarlo:
echo  1. Entra al detalle de una empresa (clic en su nombre desde la lista)
echo     -- deberia verse una seccion nueva "Obligaciones de esta empresa"
echo     con un boton "Agregar". Agrega por ejemplo Planilla con regla
echo     "Cronograma SUNAT".
echo  2. Ve a "Tareas" en el menu de la izquierda y presiona "Generar
echo     tareas del mes" -- deberia aparecer la tarea de Planilla con la
echo     misma fecha que ya ves en el modulo Cronograma para esa empresa.
echo  3. Haz clic en el circulo de la izquierda de una tarea para marcarla
echo     completada, o haz clic en la tarea para editar prioridad/fecha/
echo     observaciones.
echo  4. Confirma tambien que las empresas inactivas o con "Baja de
echo     Oficio" ya no aparecen en http://localhost:3000/cronograma.
echo  5. Entra al Dashboard (http://localhost:3000/dashboard) -- deberias
echo     ver 4 tarjetas de color (verde/ambar/rosa/teal) arriba, y debajo
echo     el panel "Avance de Cumplimiento" con el selector de periodo.
echo  6. Entra al Cronograma (http://localhost:3000/cronograma) -- cada
echo     dia con vencimientos deberia mostrar hasta 3 nombres de empresa
echo     en chips de colores, no solo un numero.
echo ---------------------------------------
pause
exit /b 0

:main
echo ---------------------------------------
echo Paso 1/3: Levantando backend...
echo ---------------------------------------
docker-compose up -d backend
ping -n 6 127.0.0.1 >nul

echo.
echo ---------------------------------------
echo Paso 2/3: Migracion de base de datos (agrega empresa_obligaciones +
echo tarea_obligaciones) -- reintenta hasta 3 veces:
echo ---------------------------------------
docker-compose exec -T backend alembic current
set intentos_migracion=0
:intentar_migracion
set /a intentos_migracion+=1
echo.
echo --- Intento %intentos_migracion%/3 ---
docker-compose exec -T backend alembic upgrade head
if errorlevel 1 (
    if %intentos_migracion% lss 3 (
        echo Fallo, esperando 5 segundos y reintentando...
        ping -n 6 127.0.0.1 >nul
        goto intentar_migracion
    )
    echo Se agotaron los 3 intentos -- revisa el error de arriba.
)
echo.
echo Revision DESPUES de aplicar (deberia decir "0012"):
docker-compose exec -T backend alembic current

echo.
echo ---------------------------------------
echo VERIFICACION FINAL: confirmando las tablas nuevas directo en Postgres:
echo ---------------------------------------
docker-compose exec -T postgres psql -U buzon -d buzon_saas -c "SELECT to_regclass('public.empresa_obligaciones') AS tabla_empresa_obligaciones;"
docker-compose exec -T postgres psql -U buzon -d buzon_saas -c "SELECT to_regclass('public.tarea_obligaciones') AS tabla_tarea_obligaciones;"

echo.
echo ---------------------------------------
echo Paso 3/3: Reiniciando worker, scheduler y frontend (toman el codigo
echo nuevo en vivo, no hace falta reconstruir la imagen esta vez)...
echo ---------------------------------------
docker-compose restart backend worker scheduler frontend

echo.
echo Esperando a que todo termine de levantar...
ping -n 11 127.0.0.1 >nul

echo.
echo ---------------------------------------
echo Logs del backend (ultimas 30 lineas):
echo ---------------------------------------
docker-compose logs --tail=30 backend

exit /b 0
