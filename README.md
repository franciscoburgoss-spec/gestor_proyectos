# Plataforma de Proyectos de Ingeniería

Sistema de seguimiento del ciclo de vida de proyectos de ingeniería.
Orientado al uso local, personal, offline.

## Requisitos

- Python 3.7 o superior (macOS ya lo trae instalado)
- Navegador web (Safari, Chrome, Firefox)

## Instalación en macOS

**Importante:** No copies la carpeta `venv/` desde otra máquina (especialmente si es Windows o Linux). Los entornos virtuales de Python **no son portables** entre sistemas operativos. Si copiaste el proyecto desde otra máquina, borrá la carpeta `venv/` primero.

1. Abre **Terminal** (Aplicaciones → Utilidades → Terminal)
2. Navega a la carpeta del proyecto:
   ```bash
   cd /ruta/a/este/proyecto
   ```
3. Si copiaste desde otra máquina, borrá el entorno anterior:
   ```bash
   rm -rf venv
   ```
4. Crea el entorno virtual en tu Mac e instala Flask:
   ```bash
   python3 -m venv venv
   ./venv/bin/pip3 install flask
   ```
5. Inicia la aplicación:
   ```bash
   ./venv/bin/python3 app.py
   ```
6. Abre tu navegador y ve a: **http://localhost:5000**

## Instalación en Windows

**Importante:** No copies la carpeta `venv/` desde otra máquina (especialmente si es Mac o Linux). Los entornos virtuales de Python **no son portables** entre sistemas operativos.

1. Abre **Símbolo del sistema** o **PowerShell**
2. Navega a la carpeta:
   ```cmd
   cd C:\ruta\a\este\proyecto
   ```
3. Si copiaste desde otra máquina, borrá el entorno anterior:
   ```cmd
   rmdir /s /q venv
   ```
4. Crea el entorno virtual e instala Flask:
   ```cmd
   python -m venv venv
   venv\Scripts\pip install flask
   ```
5. Inicia la aplicación:
   ```cmd
   venv\Scripts\python app.py
   ```
6. Abre tu navegador y ve a: **http://localhost:5000**

## Datos

La base de datos SQLite (`data/proyectos.db`) es un archivo único.
Para trasladar todo a otra máquina, simplemente copia la carpeta completa del proyecto.

## Estructura

```
proyecto_ingenieria/
├── app.py              # Aplicación principal
├── database.py         # Inicialización de base de datos
├── schema.sql          # Esquema completo
├── data/
│   └── proyectos.db   # Base de datos SQLite
├── static/
│   └── style.css       # Estilos
└── templates/          # Pantallas HTML
    ├── base.html
    ├── index.html
    ├── proyecto.html
    ├── documento.html
    ├── solicitud.html    # Resumen de solicitud de revisión
    ├── revisar.html      # Pantalla de revisión documento por documento
    ├── config.html
    ├── cementerio.html
    └── historial.html
```

## Nomenclatura de documentos

Formato: `ACRONIMO-MODULO-REVISION-TIPO-TIPOLOGIA-VERSION`

Ejemplo: `LDV-EST-CHK-PLN-T01-V01`

**Regla para módulos globales:** Los módulos de alcance global (Mecánica de Suelos, Habilitación, Urbanización) no tienen tipología específica. Para mantener la cadena de nomenclatura intacta, usar `GLB` (global) en el campo tipología:

- `PDP-MDS-CHK-ENS-GLB-V01` ✅
- `PDP-HAB-REX-INF-GLB-V01` ✅

Esto asegura que todos los códigos sigan la misma estructura parseable y sean coherentes en la plataforma.

## Uso básico

### Convención de uso

**CHK = compromiso, no revisión.** Cuando llega el email solicitando checklist, creá inmediatamente la solicitud CHK con `fecha_entrada` = hoy y `fecha_limite` = la del email. Eso registra el compromiso formal. Después registrás los documentos cuando los organizás en tu carpeta. La revisión propiamente tal la hacés días después, cuando tengas tiempo.

**Estado de documentos solo por revisión.** Los documentos mutan de estado únicamente dentro de CHK, R01, R02 o REX. No se cambian a mano desde la pantalla del documento.

### Flujo paso a paso

1. **Configuración** → Agrega módulos y tipos de documento personalizados
2. **Proyectos** → Crea un proyecto con acrónimo y ruta raíz
3. **CHK (compromiso)** → Cuando llega el email de entrada, crear CHK con fecha límite
4. **Documentos** → Registrá los archivos cuando los organizás en tu carpeta (usar `GLB` para módulos globales: MDS, HAB, URB)
5. **Pendientes** → La pantalla principal muestra todas las solicitudes por revisar, ordenadas por fecha límite
6. **Revisión** → Dentro de cada solicitud, revisá documento por documento: aprueba, observa o rechaza. El estado muta automáticamente.
7. **Completar solicitud** → Cuando terminás de revisar, marcá la solicitud como completada. Si quedan documentos pendientes, te avisa pero te deja cerrar igual.
8. **Cementerio** → Documentos eliminados con razón obligatoria
9. **Backup** → Corré `./venv/bin/python backup.py` antes de cerrar la app. Guarda una copia de `proyectos.db` con fecha y hora.
10. **Historial** → Trazabilidad inmutable de todos los cambios, revisiones y decisiones

## Parar la aplicación

En la Terminal, presiona **Control + C**.

---

Fran x Schema 🖤
