# 🗺️ System Map + Workflow — Plataforma de Ingeniería

> Versión: 2026-05-04 | Estado: Fase 5 completada con fixes de producción

---

## 📐 System Map — Entidades y Relaciones

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PROYECTO                                         │
│  ├─ id, acronimo, nombre, carpeta_raiz                                       │
│  ├─ comuna → zona_sismica (auto)                                             │
│  ├─ estado_global: activo | cerrado_aprobado | cerrado_rechazado             │
│  ├─ estado_flujo: sin_solicitud | en_chk | en_r01 | en_r02 | en_rex         │
│  ├─ motivo_cierre, fecha_cierre                                              │
│  └─ notas                                                                    │
│                                                                              │
│  1 ────o┬o──── N  SOLICITUD                                                 │
│         │       (CHK → R01 → R02 → REX)                                     │
│         │       [estado: ingresada | completada]                             │
│         │                                                                    │
│         │o──── N  DOCUMENTO                                                 │
│         │       código: ACR-MOD-FAM-ELEM-TIPO-REV-VER                        │
│         │       estado: aprobado | observado | rechazado                    │
│         │       [alerta si tipología no existe en proyecto]                 │
│         │                                                                    │
│         │o──── N  ELEMENTO_PROYECTO                                         │
│         │       T01..TN (auto) | PRO (auto) | catálogo (manual)             │
│         │                                                                    │
│         │o──── N  HISTORIAL                                                  │
│         │       [inmutable — trazabilidad total]                            │
│         │                                                                    │
│         └o──── 0..1 ACTA (por solicitud completada)                         │
│                 [Markdown auto-generado]                                   │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                         TAREAS (módulo independiente)                        │
│  ├─ asunto, fecha_solicitud, fecha_limite, notas                            │
│  ├─ estado: pendiente → en_progreso → completada                           │
│  └─ [editable: asunto, fechas, notas]                                       │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                        JORNADA (módulo independiente)                        │
│  ├─ fecha, entrada, salida                                                   │
│  ├─ estado: trabajado | feriado | permiso                                    │
│  ├─ [editable manualmente: entrada/salida por día]                           │
│  └─ Total horas lun–vie auto-calculado                                       │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                         CEMENTERIO                                             │
│  ├─ documentos_eliminados (soft delete con razón)                            │
│  └─ [restaurable → vuelve a documentos con mismo ID]                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Diagrama de Estados — Proyecto

```
┌─────────┐     Crear CHK      ┌─────────┐
│  ACTIVO │ ─────────────────→ │ en_chk  │
│sin_sol  │ ← Completa CHK ── │         │
└─────────┘     Crear R01      └─────────┘
     │                          Completa R01
     │                              ↓
     │                          ┌─────────┐
     │                          │ en_r01  │
     │                          └─────────┘
     │                          Completa R02
     │                              ↓
     │                          ┌─────────┐
     │                          │ en_r02  │
     │                          └─────────┘
     │                          Si hay rechazos
     │                              ↓
     │                          ┌─────────┐
     │                          │ en_rex  │
     │                          └─────────┘
     │                          Completa REX
     │                              ↓
     └────────────────────────→ ┌──────────────┐
        Cerrar proyecto         │ CERRADO      │
                                │(aprob/rech)  │
                                └──────────────┘
```

---

## 🔄 Diagrama de Estados — Documento

```
┌──────────┐
│ INGRESADO│ (estado inicial al crear)
└────┬─────┘
     │ CHK / R01 / R02 / REX
     ├─→ aprobado (congelado, no se revisa más)
     ├─→ observado (pasa a siguiente revisión)
     └─→ rechazado (pasa a REX o permanece)
```

> **Regla de oro:** Un documento aprobado no vuelve a aparecer en revisiones posteriores. Está congelado.

---

## 🔀 Flujo de Datos — Crear Solicitud Completa

```
1. Usuario crea Solicitud CHK en Proyecto X
   └→ Registro en historial: "Solicitud CHK#1 creada"
   └→ estado_flujo del proyecto cambia a "en_chk"

2. Usuario crea 5 Documentos (T01-EST-VIV-T01-MEM-00-A, ...)
   └→ Registro en historial: "Documento ... ingresado" (x5)

3. Usuario inicia Revisión CHK
   └→ Para cada doc: selecciona aprobado/observado/rechazado
   └→ Registro en revisiones_aplicadas + historial

4. Usuario completa Solicitud CHK
   └→ Solicitud pasa a "completada"
   └→ Acta auto-generada (Markdown)
   └→ Email tipo generado (TXT descargable)
   └→ estado_flujo recalculado → sin_solicitud (si no hay más)

5. Usuario crea Solicitud R01
   └→ Solo documentos NO aprobados aparecen para revisar
   └→ Documentos aprobados en CHK quedan congelados
```

---

## 👤 Workflow — Uso Diario del Usuario

### ☀️ Mañana — Inicio de jornada

```
Jornada → Entrada (ficha automático con hora actual)
    └→ Si olvidaste fichar: Editar hora manualmente (input time)
    └→ Si es feriado/permiso: marcar antes de fichar
```

### 📥 Recibir solicitud del Coordinador

```
Proyecto → "Nueva solicitud"
    ├─ Tipo: CHK | R01 | R02 | REX
    ├─ Fecha límite: [opcional, con validación >= fecha entrada]
    ├─ Notas: [opcional]
    └→ Crear

    ⚠️ Si ya hay CHK activa sin completar → BLOQUEADO
    ✅ Si es CHK duplicada → solo permite completar la actual primero
```

### 📄 Cargar documentos

```
Proyecto → Documentos → Crear documento
    ├─ Acrónimo: [auto desde proyecto]
    ├─ Módulo: dropdown (EST, MDS, HAB, URB, ADM)
    ├─ Revisión: dropdown (CHK, R01, R02, REX)
    ├─ Tipo documento: dropdown (MEM, PLA, INF, etc.)
    ├─ Elemento: dropdown de elementos DEL PROYECTO
    │   └→ Alerta amarilla si seleccionas tipología inexistente
    ├─ Versión: A, B, C...
    ├─ Título: libre
    └─ Ruta física: libre (solo referencia, no sube archivo)

    Código generado auto: ACR-MOD-FAM-ELEM-TIPO-REV-VER
    Ej: PBL-EST-VIV-T01-MEM-00-A
```

### 🔍 Revisar documentos

```
Solicitud → Iniciar revisión
    └→ Lista solo documentos: activos + no aprobados + sin revisión en esta solicitud

    Para cada documento:
    ├─ Resultado: aprobado | observado | rechazado
    ├─ Comentarios: [opcional]
    └→ Registrar

    Ya revisados aparecen con "Actualizar" (puedes cambiar opinión)

Solicitud → Completar
    ├─ Si quedan pendientes: advertencia pero permite completar
    ├─ Acta generada automáticamente
    ├─ Email tipo generado (TXT listo para Outlook)
    └→ Estado de flujo del proyecto actualizado
```

### 📝 Tareas extra (no relacionadas a proyectos)

```
Tareas → Nueva tarea
    ├─ Asunto: libre
    ├─ Fecha solicitud: editable manualmente (default hoy)
    ├─ Fecha límite: opcional
    ├─ Notas: opcional
    └→ Crear

    Acciones por tarea:
    ├─ Iniciar (pendiente → en_progreso)
    ├─ Completar (en_progreso → completada)
    ├─ Reactivar (completada → pendiente)
    ├─ Editar (asunto, fechas, notas)
    └─ Eliminar (sin confirmación de doble paso, cuidado)
```

### 📅 Lunes — Reporte semanal

```
Banner dorado automático en Jornada y navbar:
    "📅 Es lunes. ¿Ya enviaste tu reporte semanal?"

Jornada → Generar reporte
    └→ Descarga TXT con:
        - Jornada laboral (lun–vie de semana anterior)
        - Tareas completadas esa semana
        - Solicitudes de proyectos finalizadas esa semana
        - Formato listo para copiar a Outlook
```

### 🔧 Correcciones y errores

```
┌────────────────────┬────────────────────────────────────────────────────────┐
│ Error              │ Solución                                               │
├────────────────────┼────────────────────────────────────────────────────────┤
│ Proyecto mal       │ Proyecto → Editar → cambiar nombre, carpeta, comuna   │
│ creado             │ (zona sísmica auto-calculada)                         │
├────────────────────┼────────────────────────────────────────────────────────┤
│ Falta elemento     │ Editar proyecto → Agregar desde catálogo              │
│ en proyecto        │ (dropdown familia + elemento, con validación)        │
├────────────────────┼────────────────────────────────────────────────────────┤
│ Documento mal      │ Documento → Eliminar → Cementerio (con razón)          │
│ cargado            │ Cementerio → Restaurar (recupera mismo ID)             │
├────────────────────┼────────────────────────────────────────────────────────┤
│ Hora de entrada    │ Jornada → editar hora manualmente (input time)         │
│ mal fichada        │                                                         │
├────────────────────┼────────────────────────────────────────────────────────┤
│ Tarea con fecha    │ Tareas → Editar → cambiar fecha_solicitud o límite    │
│ equivocada         │                                                         │
├────────────────────┼────────────────────────────────────────────────────────┤
│ Solicitud con      │ Solicitud → Editar → cambiar fecha límite o notas      │
│ fecha límite mal   │ (tipo e iteración no editables — trazabilidad)         │
├────────────────────┼────────────────────────────────────────────────────────┤
│ Alerta tipologías  │ Proyecto → revisar documentos con tipología T0X       │
│ amarilla           │ inexistente → corregir o ajustar num_tipologias      │
└────────────────────┴────────────────────────────────────────────────────────┘
```

---

## 🛡️ Reglas de Protección (Hardcoded)

```
1. CHK duplicada bloqueada
   → No puedes crear CHK si hay una CHK activa sin completar

2. Fecha límite >= fecha entrada
   → Solicitud no puede vencer antes de crearse

3. Documento aprobado = congelado
   → No aparece en revisiones posteriores

4. Cementerio requiere razón
   → Todo documento eliminado lleva motivo

5. Restauración conserva ID
   → Misma trazabilidad, mismo historial

6. Matriz de compatibilidad
   → EST solo VIV/REC/OBR/GEN
   → MDS solo TER/GEN
   → HAB solo TER/OBR/REC/GEN
   → URB solo URB/GEN
   → ADM solo GEN

7. Configuración básica protegida
   → Módulos y tipos tienen UNIQUE en código
```

---

## 📊 Métricas del Sistema (Post-Implementación)

| Componente              | Estado     |
|-------------------------|------------|
| Proyectos + Elementos   | ✅ Estable  |
| Solicitudes + Revisiones| ✅ Estable  |
| Documentos + Códigos    | ✅ Estable  |
| Cementerio + Restaurar  | ✅ Nuevo    |
| Configuración (mód/tip) | ✅ Fixeado  |
| Tareas + Edición        | ✅ Nuevo    |
| Jornada + Edición manual| ✅ Nuevo    |
| Reporte semanal auto    | ✅ Estable  |
| Validación tipologías   | ✅ Nuevo    |
| Alertas visuales        | ✅ Nuevo    |
| System Map              | ✅ Este doc  |

---

*Generado por Schema el 2026-05-04. Para actualizar: modificar este archivo directamente.*
