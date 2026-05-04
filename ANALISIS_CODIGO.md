# 🔍 Análisis de Código - Plataforma de Proyectos de Ingeniería

## 📊 Resumen Ejecutivo

**Estado general:** Código funcional y bien estructurado, pero con varios bugs de borde, inconsistencias entre frontend/backend y funcionalidades declaradas pero no implementadas.

---

## 🐛 BUGS CONFIRMADOS

### 1. **CRÍTICO: `agregar_modulo` y `agregar_tipo` NO EXISTEN** (config.html líneas 12, 24)
- El template `config.html` referencia `url_for('agregar_modulo')` y `url_for('agregar_tipo')`
- **NO hay rutas en `app.py` que manejen estos endpoints**
- Resultado: Al enviar el formulario, Flask devolverá 404
- **Impacto:** Alta — Configuración básica rota

### 2. **CRÍTICO: Ruta `reporte_semanal` devuelve template vacío** (app.py línea ~1048)
- La ruta `/reporte/semanal` solo renderiza `reporte_semanal.html`
- No valida si hay datos para generar, no muestra preview
- El usuario debe hacer click en "Descargar" sin saber si hay contenido
- **Impacto:** Media — UX confusa

### 3. **Vacío lógico en `reporte_semanal/generar`** — No maneja semanas sin datos
- Si no hay jornada, tareas ni solicitudes, genera un TXT vacío con solo encabezado
- No hay mensaje al usuario de "no hay actividades esta semana"

### 4. **Bug en `editar_proyecto` — Doble submit del mismo formulario**
- El formulario de edición incluye tanto los campos básicos del proyecto COMO el selector de elemento del catálogo
- Ambos usan el mismo `<form>` y `method="POST"` al mismo endpoint
- Si el usuario quiere solo editar el nombre, igual se ejecuta la lógica de agregar elemento (que chequea `familia_elem` y `codigo_elem`)
- **Resultado:** Si el usuario deja el selector de familia/elemento en "— Seleccionar —" pero hay valores stale, puede agregar elementos accidentalmente
- **Impacto:** Media — Lógica de formulario mezclada

### 5. **CSS: Variables inconsistentes**
- `:root` define `--text-muted: #777777`
- Pero en varios lugares del CSS se usa `var(--muted)` que **no existe**
- Ejemplo: `.small` en index.html usa `style="color:var(--muted);"`
- **Impacto:** Baja — Colores fallback a negro o heredados, feo pero no crítico

### 6. **Bug de navegación: Botón "Agregar" en editar proyecto**
- El botón "Agregar" elemento está DENTRO del formulario principal de edición
- Si el usuario selecciona familia y elemento y aprieta "Agregar", en realidad hace submit de TODO el formulario (nombre, carpeta, etc.) más el elemento
- No hay un endpoint separado `POST /proyecto/<id>/elemento`
- **Impacto:** Media — Funciona pero es confuso y puede sobreescribir cambios

---

## 🔍 VACÍOS EN LA LÓGICA

### 1. **Falta validación de tipologías de vivienda (Fran lo mencionó)**
- En `crear_proyecto`, `num_tipologias` se convierte a int sin límite superior razonable (max 20 en HTML pero no en backend)
- No se valida que las tipologías generadas (T01, T02...) correspondan a lo que espera el usuario
- No hay alerta si se encuentran tipologías no esperadas (como T03 cuando se pidieron 2)
- **Estado:** Sin implementar. Fran pidió: *"validación de tipologías de vivienda (T01, T02) con alertas si encuentra otras no esperadas"*

### 2. **No hay endpoint para editar/eliminar elementos de un proyecto**
- Una vez creados, los elementos (T01, PRO, SMU...) no se pueden:
  - Renombrar
  - Reordenar
  - Eliminar (con razón)
  - Cambiar de familia
- **Impacto:** Media — Si se equivoca al crear, debe editar la BD manualmente

### 3. **No hay endpoint para editar/eliminar tareas**
- Las tareas se pueden cambiar de estado y eliminar
- Pero **no se pueden editar** los campos (asunto, fecha_limite, notas)
- Fran pidió poder editar fechas manualmente para agregar tareas retroactivas
- **Estado:** Parcial — Crear sí, editar no

### 4. **Jornada: No se puede editar horas manualmente**
- Si Fran fichó mal la entrada (08:00 en vez de 08:30), no hay forma de corregirlo
- Solo se puede marcar feriado/permiso, no editar horas específicas
- **Impacto:** Media — Errores de dedo no corregibles

### 5. **No hay validación de feriados reales**
- Los feriados se marcan manualmente día por día
- No hay integración con calendario de feriados de Chile
- Fran podría olvidar marcar un feriado y calcular mal las horas
- **Impacto:** Baja — Feature nice-to-have

### 6. **Falta protección de combinaciones sin sentido (parcialmente implementada)**
- `MATRIZ_COMPATIBILIDAD` valida módulo-familia al crear documento
- Pero **no valida**:
  - Revisión (CHK, R01, R02, REX) vs tipo de documento
  - Familia vs tipo de documento (ej: URB + MEM no tiene sentido)
  - Elemento vs módulo (ej: TOP + VIV no tiene sentido)
- **Impacto:** Baja — Solo afecta a documentos mal registrados

### 7. **Cementerio: No se puede restaurar documentos**
- Documentos eliminados van a `documentos_eliminados`
- No hay endpoint `POST /documento/restaurar` para traerlos de vuelta
- Fran dijo "proteger el trabajo de un día", pero la protección es unidireccional
- **Impacto:** Media — Error de dedo en eliminación = pérdida permanente

### 8. **No hay búsqueda global**
- No hay endpoint de búsqueda por acrónimo, nombre de documento, código, etc.
- Con muchos proyectos, encontrar uno específico requiere scroll
- **Impacto:** Baja — Ahora tiene pocos proyectos

### 9. **Historial no tiene paginación**
- `ver_historial` carga TODO el historial del proyecto
- Si hay años de actividad, la página será enorme
- **Impacto:** Baja — Crecimiento futuro

### 10. **Reporte global solo incluye proyectos activos**
- `reporte_global_md` no muestra proyectos cerrados
- No hay reporte de "todos los proyectos del año"
- **Impacto:** Baja — Fran no lo pidió explícitamente

---

## ♻️ REDUNDANCIAS

### 1. **Doble cálculo de horas en jornada**
- En `jornada()` se calcula `horas` para cada día en el loop
- Luego se recalcula `total_seg` en un segundo loop
- Podría hacerse en un solo recorrido
- **Líneas:** ~970-1015 en app.py

### 2. **Query duplicada de documentos pendientes**
- En `ver_solicitud()` se hace una query para `docs_pendientes`
- En `completar_solicitud()` se hace LA MISMA query con el mismo WHERE
- Podría extraerse a una función auxiliar `_get_docs_pendientes(sol_id)`
- **Líneas:** ~640 y ~780

### 3. **Resumen de estados calculado en múltiples lugares**
- `ver_solicitud()`, `revisar_solicitud()`, `completar_solicitud()` y `generar_email()` recalculan el resumen
- Mismo patrón: contar aprobado/observado/rechazado/pendiente
- **Función candidata:** `_calcular_resumen(sol_id)`

### 4. **Formato de fechas repetido**
- `now_chile()[:10]` para fecha
- `now_chile()[:16]` para fecha+hora
- `now_chile()[11:16]` para hora
- Sin funciones helpers: `fecha_hoy()`, `hora_ahora()`

### 5. **Flash message pattern repetido**
- `flash("...", "ok")` y `flash("...", "err")` aparecen 50+ veces
- No hay helper como `_flash_ok(msg)` o `_flash_err(msg)`
- No es bug, pero es ruido visual

---

## ⚠️ FUNCIONES DECLARADAS EN SCHEMA PERO SIN IMPLEMENTAR

| Funcionalidad | Estado | Ubicación esperada | Notas |
|---------------|--------|---------------------|-------|
| `agregar_modulo` | **❌ NO EXISTE** | `app.py` + `config.html` | Ruta POST no definida |
| `agregar_tipo` | **❌ NO EXISTE** | `app.py` + `config.html` | Ruta POST no definida |
| Editar tarea | **❌ NO EXISTE** | `tareas.html` | No hay endpoint PATCH/POST para tareas |
| Restaurar documento desde cementerio | **❌ NO EXISTE** | `cementerio.html` | Solo se puede ver, no recuperar |
| Editar hora de jornada manualmente | **❌ NO EXISTE** | `jornada.html` | Solo fichar ahora o marcar feriado |
| Eliminar elemento de proyecto | **❌ NO EXISTE** | `editar_proyecto.html` | Elementos se agregan pero no quitan |
| Búsqueda global | **❌ NO EXISTE** | `base.html` | No hay input de búsqueda |
| Paginación de historial | **❌ NO EXISTE** | `historial.html` | Carga todo |
| Editar solicitud | **❌ NO EXISTE** | `solicitud.html` | Si te equivocas en la fecha, no se puede cambiar |
| Cancelar solicitud sin completar | **❌ NO EXISTE** | `solicitud.html` | Solo "completar", no "cancelar/errar" |

---

## 🔧 PROBLEMAS DE SEGURIDAD / ROBUSTEZ

### 1. **Sin autenticación**
- Cualquiera que acceda a `localhost:5000` puede ver y modificar todo
- No hay login, sesiones, ni tokens
- Fran dijo "uso personal", pero si deja la app corriendo en la oficina...
- **Mitigación:** Aceptable para uso local, pero debe documentarse

### 2. **SQL Injection potencial en filtros**
- `filtro` en `index()` se pasa directamente a la query SQL
- Aunque se usa parameter binding para el valor, el `ORDER BY` lo construye con string concatenation
- El ORDER BY es hardcodeado, no afecta, pero el patrón es riesgoso

### 3. **No hay rate limiting**
- Botón "Entrada" en jornada puede presionarse múltiples veces
- Fichar 10 veces entrada = última hora sobreescribe (no es acumulativo, pero no hay protección)

### 4. **Race condition en CHK duplicada**
- La verificación de CHK activa se hace en Python, no en SQL con UNIQUE constraint
- Si dos requests llegan simultáneamente, ambas podrían pasar la validación antes de que ninguna inserte
- **Probabilidad:** Baja (uso personal, un usuario)

---

## 📋 RECOMENDACIONES POR PRIORIDAD

### Prioridad 1 (Arreglar ya)
1. Crear rutas `POST /config/modulo` y `POST /config/tipo` o quitar formularios de config.html
2. Separar formulario de "Agregar elemento" en `editar_proyecto` a su propio endpoint
3. Agregar edición de tareas (endpoint + UI)

### Prioridad 2 (Semana próxima)
4. Agregar validación de tipologías (alerta si T0N > num_tipologias)
5. Agregar edición manual de horas en jornada
6. Agregar botón "Restaurar" en cementerio
7. Corregir CSS variable `--muted` → `--text-muted`

### Prioridad 3 (Cuando surja)
8. Extraer helpers para reducir redundancias
9. Agregar búsqueda global
10. Paginar historial
11. Agregar cancelación de solicitudes

---

## 📊 Métricas del Código

| Métrica | Valor |
|---------|-------|
| Líneas Python (app.py) | ~1050 |
| Templates | 12 |
| Tablas DB | 10 |
| Rutas Flask | ~35 |
| Funciones sin implementar | 10 |
| Bugs confirmados | 6 |
| Redundancias mayores | 5 |

---

*Análisis generado: 2026-05-04*
