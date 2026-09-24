# Guía de pruebas manuales (antes del despliegue)

Checklist para probar en el navegador todo lo hecho en la sesión de remediación
(R0-R8) y la Fase P1 (carteras, tareas desde notificación). Pensada para
correr una sola vez, de arriba hacia abajo, contra el stack local
(`docker-compose up --build`, http://localhost:3000).

No hace falta seguir un orden estricto dentro de cada sección, pero sí
conviene hacer las secciones en el orden en que aparecen (cada una da por
sentado que la anterior ya funcionó).

---

## 0. Antes de empezar

- [ ] `docker compose ps` — los 6 servicios (`postgres`, `redis`, `backend`,
      `worker`, `scheduler`, `frontend`) en estado `Up`/`healthy`.
- [ ] http://localhost:8000/health devuelve `{"status":"ok"}`.
- [ ] http://localhost:3000/login carga.

---

## 1. Cuentas y aislamiento entre tenants (regresión de R1)

1. [ ] Registrar un tenant nuevo (`/registro`) — usa un email que no hayas
       usado antes. Debe entrar directo al dashboard tras registrarte.
2. [ ] Cerrar sesión, registrar un **segundo** tenant distinto.
3. [ ] Con el segundo tenant, entrar a **Salud del sistema** (`/salud`) y
       revisar "Errores recientes" — **no debe aparecer ningún RUC del
       primer tenant** (ese fue exactamente el bug de la Fase R1).

---

## 2. Empresas

1. [ ] `/empresas` — botón "Agregar empresa": cargar un RUC de prueba (11
       dígitos) con usuario/clave SOL cualquiera (no hace falta que sean
       reales para esta prueba de UI).
2. [ ] Botón "Importar desde Excel" — probar con el archivo de columnas
       RUC/usuario/clave/razón social que ya usa el equipo. Confirmar que
       las que ya existían no se duplican.
3. [ ] Card de una empresa: confirmar que muestra razón social, RUC,
       chips de pendientes/mensajes/consultas.
4. [ ] **Botón "Ir a SUNAT"** (fix de esta sesión):
       - Primer clic del día: puede tardar 15-30s (descubrimiento en vivo).
       - Haz clic en "Ir a SUNAT" de **otra** empresa enseguida después —
         debería ser **notablemente más rápido** que el primero (el
         prewarm se re-dispara solo tras cada uso). Si sigue tardando
         igual en el segundo clic, algo no quedó bien.
       - Si haces muchos clics seguidos y en algún momento sale un mensaje
         de "no hay cupo, intenta de nuevo" — es esperado bajo mucha carga
         simultánea, y ahora falla en ~45s en vez de colgarse 4 minutos.
5. [ ] Marcar/desmarcar una empresa como "cuenta canario" y como "Buen
       Contribuyente" desde su detalle — confirmar que el toggle visual
       responde.

---

## 3. Carteras (Fase P1) — necesita un segundo usuario en el mismo tenant

No hay pantalla de "invitar a un compañero" todavía, así que para probar
esto de verdad hace falta un segundo usuario en tu mismo tenant. Si no
tienes uno a mano, pídeme que te cree uno directo en la base (es una
inserción SQL de 1 minuto) o pide a un colega que te pase su `tenant_id`.

1. [ ] Entrar al detalle de una empresa (`/empresas/{id}`) — arriba a la
       derecha debe verse un selector **"Asignado a"** con un ícono de
       persona, junto a los botones de canario/buen contribuyente.
2. [ ] Asignar la empresa a tu compañero. Recargar la página — la
       asignación debe seguir ahí.
3. [ ] Ir a `/tareas`, usar el selector **"Mi cartera / Todas las
       carteras / [email del compañero]"** — con "Mi cartera" seleccionado
       y la empresa asignada a tu compañero, no deberías ver sus tareas;
       cambiando al email del compañero, sí.
4. [ ] Volver a la empresa y desasignarla ("Sin asignar" en el selector) —
       confirmar que desaparece de ambos filtros de cartera.

---

## 4. Crear tarea desde una notificación (Fase P1)

1. [ ] Entrar al detalle de una empresa que tenga mensajes en el buzón.
2. [ ] Junto a un mensaje, hacer clic en el ícono de "Crear tarea"
       (portapapeles con un +).
3. [ ] En el modal: el título viene precargado con el asunto del mensaje.
       Dejar la fecha de vencimiento **vacía** a propósito (así se prueba
       que el sistema no inventa un plazo) y guardar.
4. [ ] El ícono junto a ese mensaje debe cambiar a un check verde ("Ver
       tarea") — hacer clic debe llevar a `/tareas` y la tarea nueva debe
       estar en la lista (sin fecha, tipo "notificación").
5. [ ] Repetir el paso 2-3 sobre el **mismo mensaje** — debe fallar (ya
       tiene una tarea), no debe crear una segunda.
6. [ ] Editar esa tarea desde `/tareas` y ahora sí cargarle una fecha de
       vencimiento real (simulando que ya revisaste el documento).
7. [ ] Ir a `/cronograma`, navegar al mes de esa fecha — la tarea debe
       aparecer en el calendario con un color distinto (ámbar) al de los
       vencimientos oficiales de SUNAT, y en el panel de detalle del día
       debe decir "Tarea" en vez de un grupo de RUC.

---

## 5. Tareas y cronograma en general

1. [ ] `/tareas` — botón "Generar tareas del mes": si tienes alguna
       obligación configurada (Planilla/AFP/SBS) en alguna empresa, debe
       crear las tareas del mes sin duplicar si lo aprietas dos veces.
2. [ ] Marcar una tarea como completada y como pendiente de nuevo — el
       ícono y el tachado deben responder.
3. [ ] `/cronograma` — navegar mes anterior/siguiente, botón "Hoy",
       botón "Sincronizar {año}" (por si el cronograma oficial no está
       cargado). Hacer clic en un día con vencimientos abre el panel de
       detalle abajo.
4. [ ] Dashboard (`/dashboard`) — "Avance de Cumplimiento" debe reflejar
       las tareas del mes actual generadas en el paso 1.

---

## 6. Salud del sistema

1. [ ] `/salud` — revisar tasa de éxito del canario por flujo, tasa de
       éxito de consultas normales, y "Documentos recientes".
2. [ ] Botón para correr el canario a mano — después de este trabajo
       debería tardar ~70s y devolver éxito (ya se probó un login real
       durante esta sesión, RUC 10711864496, funcionó bien).
3. [ ] Confirmar (repitiendo el paso de la sección 1) que un tenant
       distinto **no ve** estos mismos datos como propios — cada uno debe
       ver solo lo suyo.

---

## 7. Cosas que NO se prueban desde el navegador (a propósito)

- Los endpoints `/admin/chequeo-nocturno`, `/admin/enviar-resumenes`,
  `/admin/canario/ejecutar` y `/admin/limpieza-diagnosticos` son
  staff-only (Fase R2/R7) — no tienen botón en el tablero, se llaman con
  `curl`/Postman usando el token de una cuenta marcada
  `es_staff_plataforma=true` (hoy: `lconhuay@lckadvisors.com`).
- El build de producción del frontend (`next build`) y el backend sin
  `--reload` ya se probaron en la Fase R4 — no hace falta repetirlo a mano
  ahora, se vuelve a verificar solo cuando lleguemos a la Fase de
  despliegue real.

---

## Si algo falla

Anotar: qué paso, qué esperabas, qué pasó en realidad, y si hay algo en la
consola del navegador (F12 → Console) o en `docker compose logs -f backend`
(o `worker`/`frontend` según corresponda) en el momento del fallo — con eso
alcanza para diagnosticar sin tener que reproducirlo de nuevo desde cero.
