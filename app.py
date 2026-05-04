# -*- coding: utf-8 -*-
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_file, session
import io
from fpdf import FPDF
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import zipfile
import json
import logging
import csv
from logging.handlers import RotatingFileHandler

from utils import now_chile, dias_habiles, ascii_safe

TZ_CHILE = ZoneInfo("America/Santiago")


# ──────────────────────────────────────────────────────────────
# CONSTANTES DE DOMINIO
# ──────────────────────────────────────────────────────────────

# Familias permitidas por módulo (protección contra combinaciones sin sentido)
MATRIZ_COMPATIBILIDAD = {
    "EST": {"VIV", "REC", "OBR", "GEN"},
    "MDS": {"TER", "GEN"},
    "HAB": {"TER", "OBR", "REC", "GEN"},
    "URB": {"URB", "GEN"},
    "ADM": {"GEN"},
}

# Orden jerárquico de estados de flujo (para UI y lógica)
ESTADOS_FLUJO_ORDEN = {
    "sin_solicitud": 0,
    "en_chk": 1,
    "en_r01": 2,
    "en_r02": 3,
    "en_rex": 4,
    "cerrado": 99,
}


def _actualizar_estado_flujo(proyecto_id, db):
    """Recalcula y guarda el estado de flujo del proyecto según solicitudes activas."""
    sol = db.execute(
        """SELECT tipo FROM solicitudes 
           WHERE proyecto_id = ? AND estado != 'completada'
           ORDER BY CASE tipo 
             WHEN 'REX' THEN 4 
             WHEN 'R02' THEN 3 
             WHEN 'R01' THEN 2 
             WHEN 'CHK' THEN 1 
             ELSE 0 
           END DESC 
           LIMIT 1""",
        (proyecto_id,)
    ).fetchone()
    if sol:
        nuevo = f"en_{sol['tipo'].lower()}"
    else:
        nuevo = "sin_solicitud"
    db.execute(
        "UPDATE proyectos SET estado_flujo = ? WHERE id = ?",
        (nuevo, proyecto_id)
    )
    db.commit()


def generar_acta_md(proyecto, sol, revisiones, docs_pendientes, resumen):
    """Genera acta de revisión en Markdown."""
    lines = [f"# Acta de Revisión: {proyecto['acronimo']}", ""]
    lines.append(f"**Proyecto:** {proyecto['nombre']}  ")
    lines.append(f"**Revisión:** {sol['tipo']} #{sol.get('numero_iteracion','')}  ")
    lines.append(f"**Fecha:** {now_chile()[:10]}  ")
    lines.append(f"**Comuna:** {proyecto.get('comuna','-')}  ")
    lines.append("")
    lines.append("## Resumen")
    for k in ["aprobado", "observado", "rechazado", "pendiente"]:
        lines.append(f"- **{k.capitalize()}:** {resumen.get(k,0)}")
    lines.append("")
    if revisiones:
        lines.append("## Documentos Revisados")
        lines.append("")
        for r in revisiones:
            lines.append(f"### {r['codigo_completo']} — {r['titulo']}")
            lines.append(f"- **Resultado:** {r['resultado']}")
            if r.get('comentarios'):
                lines.append(f"- **Comentarios:** {r['comentarios']}")
            lines.append("")
    if docs_pendientes:
        lines.append("## Documentos Pendientes de Revisión")
        for d in docs_pendientes:
            lines.append(f"- {d['codigo_completo']} — {d['titulo']}")
        lines.append("")
    lines.append("---")
    lines.append("*Acta generada automáticamente por la Plataforma de Ingeniería*")
    return "\n".join(lines)


def guardar_acta(proyecto_id, sol_id, contenido_md, db):
    """Guarda el acta en la tabla ACTAS."""
    db.execute(
        "INSERT INTO actas (proyecto_id, solicitud_id, tipo, contenido_resumen, fecha_generacion) VALUES (?,?,?,?,?)",
        (proyecto_id, sol_id, "auto", contenido_md, now_chile())
    )
    db.commit()


# ──────────────────────────────────────────────────────────────
# CONFIGURACION
# ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
SECRET_KEY_FILE = BASE_DIR / ".secret_key"

if SECRET_KEY_FILE.exists():
    SECRET_KEY = SECRET_KEY_FILE.read_text().strip()
else:
    SECRET_KEY = os.urandom(32).hex()
    SECRET_KEY_FILE.write_text(SECRET_KEY)

# Nombre de usuario para reportes y emails (editable)
USER_NAME_FILE = BASE_DIR / ".user_name"
if USER_NAME_FILE.exists():
    USER_NAME = USER_NAME_FILE.read_text().strip()
else:
    USER_NAME = "Usuario"
    USER_NAME_FILE.write_text(USER_NAME)


# Cargar comunas con zona sísmica
COMUNAS_PATH = BASE_DIR / "static" / "comunas.json"
if COMUNAS_PATH.exists():
    with open(COMUNAS_PATH, "r", encoding="utf-8") as f:
        COMUNAS_DATA = json.load(f)
else:
    COMUNAS_DATA = {"comunas": []}

COMUNAS = sorted([c["nombre"] for c in COMUNAS_DATA.get("comunas", [])])
ZONAS = {c["nombre"]: c["zona"] for c in COMUNAS_DATA.get("comunas", [])}


app = Flask(__name__)
app.secret_key = SECRET_KEY

# Configuracion de logging a archivo rotativo
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
log_handler = RotatingFileHandler(
    LOG_DIR / "app.log",
    maxBytes=1_000_000,  # 1 MB
    backupCount=5
)
log_handler.setLevel(logging.INFO)
log_handler.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)s [%(pathname)s:%(lineno)d] %(message)s"
))
app.logger.addHandler(log_handler)
app.logger.setLevel(logging.INFO)

DATABASE = BASE_DIR / "data" / "proyectos.db"
SCHEMA = BASE_DIR / "schema.sql"

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(str(DATABASE))
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db

@app.after_request
def add_cache_headers(response):
    """Agrega cache headers a archivos estaticos para reducir I/O de disco."""
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(str(DATABASE))
    with open(SCHEMA, "r", encoding="utf-8") as f:
        db.executescript(f.read())
    db.commit()
    db.close()

def migrate_db():
    """Migra columnas básicas de proyectos. Este release requiere RESET limpio
    por cambio de esquema en documentos (familia+elemento). Borrar proyectos.db manualmente."""
    db = sqlite3.connect(str(DATABASE))
    cols = db.execute("PRAGMA table_info(proyectos)").fetchall()
    col_names = [c[1] for c in cols]
    if "motivo_cierre" not in col_names:
        db.execute("ALTER TABLE proyectos ADD COLUMN motivo_cierre TEXT")
        db.commit()
    if "comuna" not in col_names:
        db.execute("ALTER TABLE proyectos ADD COLUMN comuna TEXT")
        db.commit()
    if "zona_sismica" not in col_names:
        db.execute("ALTER TABLE proyectos ADD COLUMN zona_sismica INTEGER")
        db.commit()
    if "estado_flujo" not in col_names:
        db.execute("ALTER TABLE proyectos ADD COLUMN estado_flujo TEXT DEFAULT 'sin_solicitud'")
        db.commit()

    # Crear tablas nuevas si no existen (para migración sin reset)
    db.execute("""
        CREATE TABLE IF NOT EXISTS tareas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asunto TEXT NOT NULL,
            fecha_solicitud DATE NOT NULL,
            fecha_limite DATE,
            estado TEXT DEFAULT 'pendiente',
            notas TEXT,
            fecha_creacion TIMESTAMP DEFAULT (datetime('now','localtime')),
            fecha_completada TIMESTAMP,
            CHECK (estado IN ('pendiente', 'en_progreso', 'completada'))
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS jornada (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha DATE NOT NULL UNIQUE,
            entrada TIME,
            salida TIME,
            estado TEXT DEFAULT 'trabajado',
            notas TEXT,
            CHECK (estado IN ('trabajado', 'feriado', 'permiso'))
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_tareas_estado ON tareas(estado)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_jornada_fecha ON jornada(fecha)")
    db.execute("""
        CREATE TABLE IF NOT EXISTS catalogo_elementos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            familia TEXT NOT NULL,
            codigo TEXT NOT NULL,
            nombre TEXT NOT NULL,
            activo INTEGER DEFAULT 1,
            UNIQUE(familia, codigo)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_catalogo_familia ON catalogo_elementos(familia)")
    # Insertar catálogo inicial si está vacío
    count = db.execute("SELECT COUNT(*) FROM catalogo_elementos").fetchone()[0]
    if count == 0:
        db.executescript("""
            INSERT INTO catalogo_elementos (familia, codigo, nombre) VALUES
            ('REC', 'SMU', 'Sede Social'),
            ('REC', 'QUI', 'Quincho'),
            ('REC', 'SAU', 'Sala de Usos Múltiples'),
            ('OBR', 'MUR', 'Muros de Contención'),
            ('OBR', 'EST', 'Estanques'),
            ('OBR', 'BOD', 'Bodega'),
            ('OBR', 'SAL', 'Sistema Alcantarillado'),
            ('URB', 'VIA', 'Vías'),
            ('URB', 'PAR', 'Parques / Áreas Verdes'),
            ('URB', 'VER', 'Veredas / Aceras'),
            ('TER', 'TOP', 'Topografía'),
            ('TER', 'RAS', 'Rastreo'),
            ('GEN', 'PRO', 'Proyecto General');
        """)
    db.commit()
    db.close()

# ──────────────────────────────────────────────────────────────
# INICIO
# ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    db = get_db()
    filtro = request.args.get("filtro", "").strip().upper()

    # Proyectos activos con su solicitud activa (estado != completada)
    sql = """
        SELECT p.*, s.tipo as sol_tipo, s.numero_iteracion as sol_iter, s.estado as sol_estado
        FROM proyectos p
        LEFT JOIN solicitudes s ON p.id = s.proyecto_id AND s.estado != 'completada'
        WHERE p.estado_global = 'activo'
    """
    params = []
    if filtro == "SIN_SOLICITUD":
        sql += " AND s.tipo IS NULL"
    elif filtro in ("CHK", "R01", "R02", "REX"):
        sql += " AND s.tipo = ?"
        params.append(filtro)

    sql += """
        ORDER BY
            CASE
                WHEN s.tipo = 'REX' THEN 1
                WHEN s.tipo = 'R02' THEN 2
                WHEN s.tipo = 'R01' THEN 3
                WHEN s.tipo = 'CHK' THEN 4
                ELSE 5
            END,
            p.fecha_creacion DESC
    """
    proyectos = db.execute(sql, params).fetchall()

    cerrados = db.execute(
        "SELECT * FROM proyectos WHERE estado_global != 'activo' ORDER BY fecha_cierre DESC LIMIT 10"
    ).fetchall()

    # Solicitudes pendientes de revisión, ordenadas por urgencia (fecha límite)
    pendientes_raw = db.execute("""
        SELECT s.*, p.acronimo, p.nombre as proyecto_nombre, p.id as proyecto_id,
            (SELECT COUNT(*) FROM documentos d
             WHERE d.proyecto_id = s.proyecto_id AND d.activo = 1 AND d.estado != 'aprobado'
             AND d.id NOT IN (
                 SELECT documento_id FROM revisiones_aplicadas WHERE solicitud_id = s.id
             )
            ) as docs_pendientes,
            (SELECT COUNT(*) FROM documentos d
             WHERE d.proyecto_id = s.proyecto_id AND d.activo = 1
            ) as total_docs
        FROM solicitudes s
        JOIN proyectos p ON s.proyecto_id = p.id
        WHERE s.estado != 'completada'
        ORDER BY
            CASE WHEN s.fecha_limite IS NULL THEN 1 ELSE 0 END,
            s.fecha_limite ASC,
            s.fecha_entrada ASC
    """).fetchall()

    hoy_date = datetime.strptime(now_chile()[:10], "%Y-%m-%d").date()
    pendientes = []
    for s in pendientes_raw:
        row = dict(s)
        if row['fecha_limite']:
            limite = datetime.strptime(row['fecha_limite'], "%Y-%m-%d").date()
            dias = dias_habiles(hoy_date, limite)
            row['dias_habiles'] = dias
            if dias < 0:
                row['urgencia_color'] = '#757575'
                row['urgencia_texto'] = 'Vencido'
            elif dias <= 3:
                row['urgencia_color'] = '#c62828'
                row['urgencia_texto'] = f'{dias} días hábiles'
            elif dias <= 7:
                row['urgencia_color'] = '#ef6c00'
                row['urgencia_texto'] = f'{dias} días hábiles'
            else:
                row['urgencia_color'] = '#2e7d32'
                row['urgencia_texto'] = f'{dias} días hábiles'
        else:
            row['dias_habiles'] = None
            row['urgencia_color'] = '#757575'
            row['urgencia_texto'] = 'Sin límite'
        pendientes.append(row)

    # ── KPIs Dashboard ──
    kpi = {}
    kpi['proyectos_activos'] = db.execute("SELECT COUNT(*) FROM proyectos WHERE estado_global = 'activo'").fetchone()[0]
    kpi['total_documentos'] = db.execute("SELECT COUNT(*) FROM documentos WHERE activo = 1").fetchone()[0]
    estados_docs = db.execute("SELECT estado, COUNT(*) as c FROM documentos WHERE activo = 1 GROUP BY estado").fetchall()
    kpi['docs_aprobados'] = sum(r['c'] for r in estados_docs if r['estado'] == 'aprobado')
    kpi['docs_pendientes'] = sum(r['c'] for r in estados_docs if r['estado'] == 'pendiente')
    kpi['docs_rechazados'] = sum(r['c'] for r in estados_docs if r['estado'] == 'rechazado')
    kpi['solicitudes_vencidas'] = db.execute(
        "SELECT COUNT(*) FROM solicitudes WHERE estado != 'completada' AND fecha_limite < ?",
        (now_chile()[:10],)
    ).fetchone()[0]
    lunes_str = (hoy_date - timedelta(days=hoy_date.weekday())).strftime("%Y-%m-%d")
    kpi['sol_completadas_semana'] = db.execute(
        "SELECT COUNT(*) FROM solicitudes WHERE estado = 'completada' AND fecha_cierre >= ?",
        (lunes_str,)
    ).fetchone()[0]

    return render_template("index.html", proyectos=proyectos, cerrados=cerrados, pendientes=pendientes,
                           hoy=now_chile()[:10], filtro=filtro, comunas=COMUNAS, kpi=kpi)

@app.route("/proyecto/crear", methods=["POST"])
def crear_proyecto():
    db = get_db()
    acronimo = request.form["acronimo"].strip().upper()
    nombre = request.form["nombre"].strip()
    carpeta = request.form["carpeta_raiz"].strip()
    comuna = request.form.get("comuna", "").strip()
    notas = request.form.get("notas", "").strip()
    num_tipologias = request.form.get("num_tipologias", "0").strip()

    # Zona sísmica: automática desde comunas.json según la comuna seleccionada
    zona_sismica = ZONAS.get(comuna, None) if comuna else None

    try:
        db.execute(
            "INSERT INTO proyectos (acronimo, nombre, carpeta_raiz, comuna, zona_sismica, notas, fecha_creacion) VALUES (?,?,?,?,?,?,?)",
            (acronimo, nombre, carpeta, comuna, zona_sismica, notas, now_chile())
        )
        db.commit()
        proyecto = db.execute("SELECT id FROM proyectos WHERE acronimo = ?", (acronimo,)).fetchone()
        pid = proyecto["id"]

        # Crear elementos automáticamente
        # 1. Tipologías
        try:
            nt = int(num_tipologias)
        except ValueError:
            nt = 0
        if nt > 0:
            for i in range(1, nt + 1):
                cod = f"T{i:02d}"
                db.execute(
                    "INSERT INTO elementos_proyecto (proyecto_id, codigo, nombre, familia, orden) VALUES (?,?,?,?,?)",
                    (pid, cod, f"Tipología {i}", "VIV", i)
                )

        # 2. Elemento PRO (Proyecto General) siempre presente
        db.execute(
            "INSERT INTO elementos_proyecto (proyecto_id, codigo, nombre, familia, orden) VALUES (?,?,?,?,?)",
            (pid, "PRO", "Proyecto General", "GEN", 999)
        )

        db.commit()

        # Registrar en historial
        desc = f"Proyecto {acronimo} creado"
        if comuna:
            desc += f" (comuna: {comuna}"
            if zona_sismica:
                desc += f", Z{zona_sismica}"
            desc += ")"
        if nt > 0:
            desc += f" con {nt} tipologías"
        db.execute(
            "INSERT INTO historial (proyecto_id, accion, descripcion, fecha) VALUES (?,?,?,?)",
            (pid, "creacion", desc, now_chile())
        )
        db.commit()
        flash(f"Proyecto {acronimo} creado correctamente", "ok")
    except sqlite3.IntegrityError:
        flash("Ya existe un proyecto con ese acrónimo", "err")
    return redirect(url_for("index"))

# ──────────────────────────────────────────────────────────────
# PROYECTO
# ──────────────────────────────────────────────────────────────
@app.route("/proyecto/<int:proyecto_id>/editar", methods=["GET", "POST"])
def editar_proyecto(proyecto_id):
    db = get_db()
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
    if not proyecto:
        flash("Proyecto no encontrado", "err")
        return redirect(url_for("index"))

    if request.method == "POST":
        nombre = request.form["nombre"].strip()
        carpeta = request.form["carpeta_raiz"].strip()
        comuna = request.form.get("comuna", "").strip()
        notas = request.form.get("notas", "").strip()

        # Zona sísmica: automática desde comunas.json según la comuna
        nueva_zona = ZONAS.get(comuna, None) if comuna else None
        zona_anterior = proyecto["zona_sismica"]

        if not nombre or not carpeta:
            flash("Nombre y carpeta raíz son obligatorios", "err")
            return redirect(url_for("editar_proyecto", proyecto_id=proyecto_id))

        cambios = []
        if nombre != proyecto["nombre"]:
            cambios.append(f"nombre: '{proyecto['nombre']}' → '{nombre}'")
        if carpeta != proyecto["carpeta_raiz"]:
            cambios.append(f"carpeta: '{proyecto['carpeta_raiz']}' → '{carpeta}'")
        if comuna != (proyecto["comuna"] or ""):
            cambios.append(f"comuna: '{proyecto['comuna'] or '-'}' → '{comuna or '-'}'")
        if nueva_zona != zona_anterior:
            cambios.append(f"zona sísmica: Z{zona_anterior or '-'} → Z{nueva_zona or '-'}'")
        if notas != (proyecto["notas"] or ""):
            cambios.append("notas actualizadas")

        db.execute(
            "UPDATE proyectos SET nombre = ?, carpeta_raiz = ?, comuna = ?, zona_sismica = ?, notas = ? WHERE id = ?",
            (nombre, carpeta, comuna, nueva_zona, notas, proyecto_id)
        )

        if cambios:
            desc = "Proyecto editado. " + "; ".join(cambios)
            db.execute(
                "INSERT INTO historial (proyecto_id, accion, descripcion, fecha) VALUES (?,?,?,?)",
                (proyecto_id, "edicion", desc, now_chile())
            )

        db.commit()
        flash("Proyecto actualizado", "ok")
        return redirect(url_for("ver_proyecto", proyecto_id=proyecto_id))

    elementos = db.execute(
        "SELECT * FROM elementos_proyecto WHERE proyecto_id = ? ORDER BY orden, id",
        (proyecto_id,)
    ).fetchall()

    # Catálogo maestro para dropdowns condicionados
    try:
        catalogo_raw = db.execute("SELECT * FROM catalogo_elementos WHERE activo = 1 ORDER BY familia, codigo").fetchall()
    except sqlite3.OperationalError:
        catalogo_raw = []
    familias = sorted({c["familia"] for c in catalogo_raw})
    catalogo_por_familia = {}
    for c in catalogo_raw:
        catalogo_por_familia.setdefault(c["familia"], []).append({"codigo": c["codigo"], "nombre": c["nombre"]})

    return render_template("editar_proyecto.html", proyecto=proyecto, comunas=COMUNAS, elementos=elementos, familias=familias, catalogo=catalogo_por_familia)


@app.route("/proyecto/<int:proyecto_id>/elemento", methods=["POST"])
def agregar_elemento_proyecto(proyecto_id):
    db = get_db()
    familia_elem = request.form.get("familia_elemento", "").strip().upper()
    codigo_elem = request.form.get("elemento_catalogo", "").strip().upper()
    if not familia_elem or not codigo_elem:
        flash("Debes seleccionar familia y elemento", "err")
        return redirect(url_for("editar_proyecto", proyecto_id=proyecto_id))
    cat = db.execute(
        "SELECT * FROM catalogo_elementos WHERE familia = ? AND codigo = ? AND activo = 1",
        (familia_elem, codigo_elem)
    ).fetchone()
    if not cat:
        flash("Elemento no encontrado en el catálogo", "err")
        return redirect(url_for("editar_proyecto", proyecto_id=proyecto_id))
    existe = db.execute(
        "SELECT id FROM elementos_proyecto WHERE proyecto_id = ? AND codigo = ?",
        (proyecto_id, codigo_elem)
    ).fetchone()
    if existe:
        flash(f"El elemento {codigo_elem} ya existe en este proyecto", "err")
        return redirect(url_for("editar_proyecto", proyecto_id=proyecto_id))
    db.execute(
        "INSERT INTO elementos_proyecto (proyecto_id, codigo, nombre, familia, orden) VALUES (?,?,?,?,?)",
        (proyecto_id, cat["codigo"], cat["nombre"], cat["familia"], 100)
    )
    db.execute(
        "INSERT INTO historial (proyecto_id, accion, descripcion, fecha) VALUES (?,?,?,?)",
        (proyecto_id, "elemento_agregado", f"Elemento {cat['codigo']} ({cat['nombre']}) agregado desde catálogo", now_chile())
    )
    db.commit()
    flash(f"Elemento {codigo_elem} agregado", "ok")
    return redirect(url_for("editar_proyecto", proyecto_id=proyecto_id))


@app.route("/proyecto/<int:proyecto_id>")
def ver_proyecto(proyecto_id):
    db = get_db()
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
    if not proyecto:
        flash("Proyecto no encontrado", "err")
        return redirect(url_for("index"))

    elementos = db.execute(
        "SELECT * FROM elementos_proyecto WHERE proyecto_id = ? ORDER BY orden, id",
        (proyecto_id,)
    ).fetchall()

    # ── Filtros de documentos ──
    filtro_estado = request.args.get("estado", "").strip().lower()
    filtro_modulo = request.args.get("modulo", "").strip().upper()
    filtro_tipo = request.args.get("tipo", "").strip().upper()

    sql_docs = """SELECT d.*, e.codigo as elem_codigo, e.nombre as elem_nombre 
           FROM documentos d 
           LEFT JOIN elementos_proyecto e ON d.elemento_id = e.id 
           WHERE d.proyecto_id = ? AND d.activo = 1"""
    params_docs = [proyecto_id]
    if filtro_estado:
        sql_docs += " AND d.estado = ?"
        params_docs.append(filtro_estado)
    if filtro_modulo:
        sql_docs += " AND d.modulo = ?"
        params_docs.append(filtro_modulo)
    if filtro_tipo:
        sql_docs += " AND d.tipo_documento = ?"
        params_docs.append(filtro_tipo)
    sql_docs += " ORDER BY d.codigo_completo"

    documentos = db.execute(sql_docs, params_docs).fetchall()

    solicitudes = db.execute(
        "SELECT * FROM solicitudes WHERE proyecto_id = ? ORDER BY fecha_entrada DESC",
        (proyecto_id,)
    ).fetchall()

    # Resumen rápido
    estados = db.execute(
        "SELECT estado, COUNT(*) as c FROM documentos WHERE proyecto_id = ? AND activo = 1 GROUP BY estado",
        (proyecto_id,)
    ).fetchall()
    resumen = {r["estado"]: r["c"] for r in estados}

    config_modulos = db.execute("SELECT * FROM config_modulos WHERE activo = 1 ORDER BY codigo").fetchall()
    config_tipos = db.execute("SELECT * FROM config_tipos_documento WHERE activo = 1 ORDER BY codigo").fetchall()

    actas = db.execute(
        "SELECT * FROM actas WHERE proyecto_id = ? ORDER BY fecha_generacion DESC",
        (proyecto_id,)
    ).fetchall()

    # Validación de tipologías: detectar documentos con tipologías no esperadas
    tipologias_validas = {e["codigo"] for e in elementos if e["familia"] == "VIV"}
    alertas_tipologias = []
    for d in documentos:
        if d["familia"] == "VIV" and d["elemento"] not in tipologias_validas:
            alertas_tipologias.append(f"{d['codigo_completo']} usa tipología {d['elemento']} que no está en el proyecto (solo hay {len(tipologias_validas)} tipologías definidas)")

    # Recuperar datos de formulario preservados tras error (documento duplicado)
    doc_form_data = session.pop("doc_form_data", None)

    return render_template("proyecto.html", proyecto=proyecto, documentos=documentos,
                           solicitudes=solicitudes, resumen=resumen,
                           config_modulos=config_modulos, config_tipos=config_tipos,
                           elementos=elementos, actas=actas,
                           num_tipologias=len([e for e in elementos if e["familia"] == "VIV"]),
                           alertas_tipologias=alertas_tipologias,
                           doc_form_data=doc_form_data,
                           filtro_estado=filtro_estado,
                           filtro_modulo=filtro_modulo,
                           filtro_tipo=filtro_tipo,
                           hoy=now_chile()[:10])

@app.route("/proyecto/<int:proyecto_id>/cerrar", methods=["POST"])
def cerrar_proyecto(proyecto_id):
    db = get_db()
    tipo = request.form["tipo"]
    motivo = request.form.get("motivo_cierre", "").strip()
    now = now_chile()
    db.execute(
        "UPDATE proyectos SET estado_global = ?, fecha_cierre = ?, motivo_cierre = ? WHERE id = ?",
        (tipo, now, motivo, proyecto_id)
    )
    desc = f"Proyecto cerrado: {tipo}"
    if motivo:
        desc += f". Motivo: {motivo}"
    db.execute(
        "INSERT INTO historial (proyecto_id, accion, descripcion, fecha) VALUES (?,?,?,?)",
        (proyecto_id, "cierre", desc, now)
    )
    db.commit()
    flash("Proyecto cerrado", "ok")
    return redirect(url_for("index"))

# ──────────────────────────────────────────────────────────────
# DOCUMENTO
# ──────────────────────────────────────────────────────────────
@app.route("/documento/crear", methods=["POST"])
def crear_documento():
    db = get_db()
    proyecto_id = int(request.form["proyecto_id"])
    acronimo = request.form["acronimo"].strip().upper()
    modulo = request.form["modulo"].strip().upper()
    revision = request.form["revision"].strip().upper()
    tipo_doc = request.form["tipo_documento"].strip().upper()
    elemento_id = request.form.get("elemento_id", "").strip()
    version = request.form["version"].strip().upper()
    titulo = request.form["titulo"].strip()
    ruta = request.form.get("ruta_fisica", "").strip()

    # Resolver elemento (familia + código)
    familia = "GEN"
    elemento = "PRO"
    elem_id_int = None
    if elemento_id:
        try:
            elem_id_int = int(elemento_id)
            elem = db.execute("SELECT * FROM elementos_proyecto WHERE id = ? AND proyecto_id = ?", (elem_id_int, proyecto_id)).fetchone()
            if elem:
                familia = elem["familia"]
                elemento = elem["codigo"]
        except ValueError:
            pass

    # Validar matriz de compatibilidad módulo-familia
    familias_permitidas = MATRIZ_COMPATIBILIDAD.get(modulo)
    if familias_permitidas and familia not in familias_permitidas:
        flash(
            f"Combinación inválida: el módulo {modulo} no admite la familia {familia}. "
            f"Familias permitidas: {', '.join(sorted(familias_permitidas))}", "err"
        )
        session["doc_form_data"] = {
            "acronimo": acronimo, "modulo": modulo, "revision": revision,
            "tipo_documento": tipo_doc, "version": version,
            "titulo": titulo, "ruta_fisica": ruta, "elemento_id": elemento_id
        }
        return redirect(url_for("ver_proyecto", proyecto_id=proyecto_id))

    codigo = f"{acronimo}-{modulo}-{familia}-{elemento}-{tipo_doc}-{revision}-{version}"

    try:
        db.execute(
            """INSERT INTO documentos
            (proyecto_id, elemento_id, codigo_completo, acronimo, modulo, familia, elemento,
             tipo_documento, revision, version, titulo, ruta_fisica, fecha_registro)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (proyecto_id, elem_id_int, codigo, acronimo, modulo, familia, elemento, tipo_doc, revision, version, titulo, ruta, now_chile())
        )
        db.commit()
        doc = db.execute("SELECT id FROM documentos WHERE codigo_completo = ?", (codigo,)).fetchone()
        db.execute(
            "INSERT INTO historial (proyecto_id, documento_id, accion, descripcion, fecha) VALUES (?,?,?,?,?)",
            (proyecto_id, doc["id"], "creacion", f"Documento {codigo} ingresado", now_chile())
        )
        db.commit()
        flash(f"Documento {codigo} registrado", "ok")
    except sqlite3.IntegrityError:
        flash(f"Ya existe un documento con código {codigo}", "err")
        session["doc_form_data"] = {
            "acronimo": acronimo, "modulo": modulo, "revision": revision,
            "tipo_documento": tipo_doc, "version": version,
            "titulo": titulo, "ruta_fisica": ruta, "elemento_id": elemento_id
        }

    return redirect(url_for("ver_proyecto", proyecto_id=proyecto_id))

@app.route("/documento/<int:doc_id>")
def ver_documento(doc_id):
    db = get_db()
    doc = db.execute("SELECT * FROM documentos WHERE id = ?", (doc_id,)).fetchone()
    if not doc:
        flash("Documento no encontrado", "err")
        return redirect(url_for("index"))

    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (doc["proyecto_id"],)).fetchone()
    historial = db.execute(
        "SELECT * FROM historial WHERE documento_id = ? ORDER BY fecha DESC",
        (doc_id,)
    ).fetchall()
    revisiones = db.execute(
        "SELECT ra.*, s.tipo as sol_tipo FROM revisiones_aplicadas ra JOIN solicitudes s ON ra.solicitud_id = s.id WHERE ra.documento_id = ? ORDER BY ra.fecha_revision DESC",
        (doc_id,)
    ).fetchall()

    return render_template("documento.html", doc=doc, proyecto=proyecto, historial=historial, revisiones=revisiones)



@app.route("/documento/<int:doc_id>/copiar_nombre")
def copiar_nombre_documento(doc_id):
    """Devuelve el nombre sugerido del documento para copiar al portapapeles."""
    db = get_db()
    doc = db.execute("SELECT * FROM documentos WHERE id = ?", (doc_id,)).fetchone()
    if not doc:
        return {"error": "Documento no encontrado"}, 404
    nombre_sugerido = f"{doc['codigo_completo']}"
    return {"nombre_sugerido": nombre_sugerido, "codigo_completo": doc["codigo_completo"], "titulo": doc["titulo"]}, 200

@app.route("/documento/<int:doc_id>/titulo", methods=["POST"])
def cambiar_titulo(doc_id):
    db = get_db()
    nuevo = request.form["titulo"].strip()
    doc = db.execute("SELECT * FROM documentos WHERE id = ?", (doc_id,)).fetchone()
    viejo = doc["titulo"]
    db.execute("UPDATE documentos SET titulo = ? WHERE id = ?", (nuevo, doc_id))
    db.execute(
        "INSERT INTO historial (proyecto_id, documento_id, accion, valor_anterior, valor_nuevo, descripcion, fecha) VALUES (?,?,?,?,?,?,?)",
        (doc["proyecto_id"], doc_id, "cambio_titulo", viejo, nuevo, f"Título cambiado de '{viejo}' a '{nuevo}'", now_chile())
    )
    db.commit()
    flash("Título actualizado", "ok")
    return redirect(url_for("ver_documento", doc_id=doc_id))

@app.route("/documento/<int:doc_id>/eliminar", methods=["POST"])
def eliminar_documento(doc_id):
    db = get_db()
    razon = request.form["razon"].strip()
    if not razon:
        flash("Debes indicar una razón para eliminar", "err")
        return redirect(url_for("ver_documento", doc_id=doc_id))

    doc = db.execute("SELECT * FROM documentos WHERE id = ?", (doc_id,)).fetchone()

    db.execute(
        """INSERT INTO documentos_eliminados
        (proyecto_id, documento_id_original, codigo_completo, titulo, ruta_fisica_original, razon_eliminacion, fecha_eliminacion)
        VALUES (?,?,?,?,?,?,?)""",
        (doc["proyecto_id"], doc_id, doc["codigo_completo"], doc["titulo"], doc["ruta_fisica"], razon, now_chile())
    )
    db.execute("UPDATE documentos SET activo = 0 WHERE id = ?", (doc_id,))
    db.execute(
        "INSERT INTO historial (proyecto_id, documento_id, accion, descripcion, fecha) VALUES (?,?,?,?,?)",
        (doc["proyecto_id"], doc_id, "eliminacion", f"Documento {doc['codigo_completo']} eliminado. Razón: {razon}", now_chile())
    )
    db.commit()
    flash("Documento eliminado y registrado en cementerio", "ok")
    return redirect(url_for("ver_proyecto", proyecto_id=doc["proyecto_id"]))

# ──────────────────────────────────────────────────────────────
# SOLICITUDES
# ──────────────────────────────────────────────────────────────
@app.route("/solicitud/crear", methods=["POST"])
def crear_solicitud():
    db = get_db()
    proyecto_id = int(request.form["proyecto_id"])
    tipo = request.form["tipo"]
    fecha_entrada = request.form["fecha_entrada"]
    fecha_limite = request.form.get("fecha_limite") or None
    notas = request.form.get("notas", "").strip()

    # Validar fechas
    if fecha_limite and fecha_limite < fecha_entrada:
        flash("La fecha límite no puede ser anterior a la fecha de entrada", "err")
        return redirect(url_for("ver_proyecto", proyecto_id=proyecto_id))

    # Verificar que no exista ya una solicitud del mismo tipo activa
    if tipo in ("R01", "R02", "REX"):
        existente = db.execute(
            "SELECT id FROM solicitudes WHERE proyecto_id = ? AND tipo = ? AND estado != 'completada'",
            (proyecto_id, tipo)
        ).fetchone()
        if existente:
            flash(f"Ya existe una solicitud {tipo} activa para este proyecto", "err")
            return redirect(url_for("ver_proyecto", proyecto_id=proyecto_id))

    # Para CHK, verificar que no haya una CHK activa sin completar
    if tipo == "CHK":
        chk_activa = db.execute(
            "SELECT id FROM solicitudes WHERE proyecto_id = ? AND tipo = 'CHK' AND estado != 'completada'",
            (proyecto_id,)
        ).fetchone()
        if chk_activa:
            flash("Ya existe una solicitud CHK activa. Complétala antes de crear una nueva.", "err")
            return redirect(url_for("ver_proyecto", proyecto_id=proyecto_id))

    # Para CHK, determinar iteración
    iteracion = 1
    if tipo == "CHK":
        max_iter = db.execute(
            "SELECT MAX(numero_iteracion) as m FROM solicitudes WHERE proyecto_id = ? AND tipo = 'CHK'",
            (proyecto_id,)
        ).fetchone()
        if max_iter and max_iter["m"]:
            iteracion = max_iter["m"] + 1

    db.execute(
        "INSERT INTO solicitudes (proyecto_id, tipo, numero_iteracion, fecha_entrada, fecha_limite, notas) VALUES (?,?,?,?,?,?)",
        (proyecto_id, tipo, iteracion, fecha_entrada, fecha_limite, notas)
    )
    db.commit()

    # Registrar en historial
    db.execute(
        "INSERT INTO historial (proyecto_id, accion, descripcion, fecha) VALUES (?,?,?,?)",
        (proyecto_id, "creacion", f"Solicitud {tipo} #{iteracion} registrada", now_chile())
    )
    db.commit()

    # Actualizar estado de flujo
    _actualizar_estado_flujo(proyecto_id, db)

    flash(f"Solicitud {tipo} registrada", "ok")
    return redirect(url_for("ver_proyecto", proyecto_id=proyecto_id))

# ──────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────────────────────
@app.route("/config")
def config():
    db = get_db()
    modulos = db.execute("SELECT * FROM config_modulos ORDER BY codigo").fetchall()
    tipos = db.execute("SELECT * FROM config_tipos_documento ORDER BY codigo").fetchall()
    catalogo = db.execute("SELECT * FROM catalogo_elementos ORDER BY familia, codigo").fetchall()
    familias = sorted({c["familia"] for c in catalogo})
    return render_template("config.html", modulos=modulos, tipos=tipos, catalogo=catalogo, familias=familias)


@app.route("/config/modulo", methods=["POST"])
def agregar_modulo():
    db = get_db()
    codigo = request.form["codigo"].strip().upper()
    nombre = request.form["nombre"].strip()
    try:
        db.execute("INSERT INTO config_modulos (codigo, nombre) VALUES (?,?)", (codigo, nombre))
        db.commit()
        flash(f"Módulo {codigo} agregado", "ok")
    except sqlite3.IntegrityError:
        flash("Ese código de módulo ya existe", "err")
    return redirect(url_for("config"))


@app.route("/config/tipo", methods=["POST"])
def agregar_tipo():
    db = get_db()
    codigo = request.form["codigo"].strip().upper()
    nombre = request.form["nombre"].strip()
    try:
        db.execute("INSERT INTO config_tipos_documento (codigo, nombre) VALUES (?,?)", (codigo, nombre))
        db.commit()
        flash(f"Tipo {codigo} agregado", "ok")
    except sqlite3.IntegrityError:
        flash("Ese código de tipo ya existe", "err")
    return redirect(url_for("config"))


@app.route("/config/elemento", methods=["POST"])
def agregar_elemento_catalogo():
    db = get_db()
    familia = request.form["familia"].strip().upper()
    codigo = request.form["codigo"].strip().upper()
    nombre = request.form["nombre"].strip()
    try:
        db.execute("INSERT INTO catalogo_elementos (familia, codigo, nombre) VALUES (?,?,?)", (familia, codigo, nombre))
        db.commit()
        flash(f"Elemento {codigo} ({nombre}) agregado al catálogo", "ok")
    except sqlite3.IntegrityError:
        flash("Esa combinación familia+código ya existe", "err")
    return redirect(url_for("config"))

# ──────────────────────────────────────────────────────────────
# CEMENTERIO
# ──────────────────────────────────────────────────────────────
@app.route("/cementerio")
def cementerio():
    db = get_db()
    pagina = max(1, int(request.args.get("pagina", 1)))
    por_pagina = 50
    offset = (pagina - 1) * por_pagina
    total = db.execute("SELECT COUNT(*) as c FROM documentos_eliminados").fetchone()["c"]
    total_paginas = (total + por_pagina - 1) // por_pagina
    eliminados = db.execute(
        """SELECT de.*, p.acronimo, p.nombre
        FROM documentos_eliminados de
        JOIN proyectos p ON de.proyecto_id = p.id
        ORDER BY de.fecha_eliminacion DESC
        LIMIT ? OFFSET ?""", (por_pagina, offset)
    ).fetchall()
    return render_template("cementerio.html", eliminados=eliminados, pagina=pagina, total_paginas=total_paginas, total=total)


@app.route("/cementerio/restaurar/<int:cementerio_id>", methods=["POST"])
def restaurar_documento(cementerio_id):
    db = get_db()
    eliminado = db.execute(
        "SELECT * FROM documentos_eliminados WHERE id = ?", (cementerio_id,)
    ).fetchone()
    if not eliminado:
        flash("Registro no encontrado en cementerio", "err")
        return redirect(url_for("cementerio"))
    db.execute(
        "UPDATE documentos SET activo = 1 WHERE id = ?",
        (eliminado["documento_id_original"],)
    )
    db.execute("DELETE FROM documentos_eliminados WHERE id = ?", (cementerio_id,))
    db.execute(
        "INSERT INTO historial (proyecto_id, documento_id, accion, descripcion, fecha) VALUES (?,?,?,?,?)",
        (eliminado["proyecto_id"], eliminado["documento_id_original"], "restauracion",
         f"Documento {eliminado['codigo_completo']} restaurado desde cementerio", now_chile())
    )
    db.commit()
    flash(f"Documento {eliminado['codigo_completo']} restaurado", "ok")
    return redirect(url_for("cementerio"))

# ──────────────────────────────────────────────────────────────
# HISTORIAL
# ──────────────────────────────────────────────────────────────
@app.route("/historial/<int:proyecto_id>")
def ver_historial(proyecto_id):
    db = get_db()
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
    pagina = max(1, int(request.args.get("pagina", 1)))
    por_pagina = 50
    offset = (pagina - 1) * por_pagina
    total = db.execute("SELECT COUNT(*) as c FROM historial WHERE proyecto_id = ?", (proyecto_id,)).fetchone()["c"]
    total_paginas = (total + por_pagina - 1) // por_pagina
    historial = db.execute("""
        SELECT h.*, d.codigo_completo as doc_codigo
        FROM historial h
        LEFT JOIN documentos d ON h.documento_id = d.id
        WHERE h.proyecto_id = ?
        ORDER BY h.fecha DESC
        LIMIT ? OFFSET ?
    """, (proyecto_id, por_pagina, offset)).fetchall()
    return render_template("historial.html", proyecto=proyecto, historial=historial,
                           pagina=pagina, total_paginas=total_paginas, total=total)

# ──────────────────────────────────────────────────────────────
# FASE 4 - REVISIONES
# ──────────────────────────────────────────────────────────────
@app.route("/solicitud/<int:sol_id>")
def ver_solicitud(sol_id):
    db = get_db()
    sol = db.execute("SELECT * FROM solicitudes WHERE id = ?", (sol_id,)).fetchone()
    if not sol:
        flash("Solicitud no encontrada", "err")
        return redirect(url_for("index"))

    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (sol["proyecto_id"],)).fetchone()

    # Revisiones aplicadas en esta solicitud
    revisiones = db.execute("""
        SELECT ra.*, d.codigo_completo, d.titulo, d.estado as doc_estado
        FROM revisiones_aplicadas ra
        JOIN documentos d ON ra.documento_id = d.id
        WHERE ra.solicitud_id = ?
        ORDER BY ra.fecha_revision DESC
    """, (sol_id,)).fetchall()

    # Documentos del proyecto que aún no tienen revisión en esta solicitud
    docs_pendientes = db.execute("""
        SELECT d.* FROM documentos d
        WHERE d.proyecto_id = ? AND d.activo = 1 AND d.estado != 'aprobado'
        AND d.id NOT IN (
            SELECT documento_id FROM revisiones_aplicadas WHERE solicitud_id = ?
        )
        ORDER BY d.codigo_completo
    """, (sol["proyecto_id"], sol_id)).fetchall()

    # Resumen rápido
    resumen = {"aprobado": 0, "observado": 0, "rechazado": 0, "pendiente": len(docs_pendientes)}
    for r in revisiones:
        resumen[r["resultado"]] = resumen.get(r["resultado"], 0) + 1

    # Buscar acta generada para esta solicitud
    acta = db.execute(
        "SELECT * FROM actas WHERE solicitud_id = ? ORDER BY fecha_generacion DESC LIMIT 1",
        (sol_id,)
    ).fetchone()

    return render_template("solicitud.html", sol=sol, proyecto=proyecto,
                           revisiones=revisiones, docs_pendientes=docs_pendientes,
                           resumen=resumen, acta=acta)


@app.route("/solicitud/<int:sol_id>/editar", methods=["GET", "POST"])
def editar_solicitud(sol_id):
    db = get_db()
    sol = db.execute("SELECT * FROM solicitudes WHERE id = ?", (sol_id,)).fetchone()
    if not sol:
        flash("Solicitud no encontrada", "err")
        return redirect(url_for("index"))
    if request.method == "POST":
        fecha_limite = request.form.get("fecha_limite") or None
        notas = request.form.get("notas", "").strip()
        db.execute(
            "UPDATE solicitudes SET fecha_limite = ?, notas = ? WHERE id = ?",
            (fecha_limite, notas, sol_id)
        )
        db.commit()
        flash("Solicitud actualizada", "ok")
        return redirect(url_for("ver_solicitud", sol_id=sol_id))
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (sol["proyecto_id"],)).fetchone()
    return render_template("editar_solicitud.html", sol=sol, proyecto=proyecto)


@app.route("/acta/<int:acta_id>")
def ver_acta(acta_id):
    db = get_db()
    acta = db.execute("SELECT * FROM actas WHERE id = ?", (acta_id,)).fetchone()
    if not acta:
        flash("Acta no encontrada", "err")
        return redirect(url_for("index"))
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (acta["proyecto_id"],)).fetchone()
    sol = db.execute("SELECT * FROM solicitudes WHERE id = ?", (acta["solicitud_id"],)).fetchone()
    return render_template("acta.html", acta=acta, proyecto=proyecto, sol=sol)


@app.route("/acta/<int:acta_id>/descargar")
def descargar_acta(acta_id):
    db = get_db()
    acta = db.execute("SELECT * FROM actas WHERE id = ?", (acta_id,)).fetchone()
    if not acta:
        flash("Acta no encontrada", "err")
        return redirect(url_for("index"))
    contenido = acta["contenido_resumen"] or ""
    buffer = io.BytesIO(contenido.encode("utf-8"))
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="text/markdown",
        as_attachment=True,
        download_name=f"acta_{acta['id']}.md"
    )


@app.route("/solicitud/<int:sol_id>/revisar")
def revisar_solicitud(sol_id):
    db = get_db()
    sol = db.execute("SELECT * FROM solicitudes WHERE id = ?", (sol_id,)).fetchone()
    if not sol:
        flash("Solicitud no encontrada", "err")
        return redirect(url_for("index"))

    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (sol["proyecto_id"],)).fetchone()

    # Documentos revisables: activos, no aprobados (congelados)
    documentos = db.execute("""
        SELECT d.*,
            (SELECT resultado FROM revisiones_aplicadas
             WHERE solicitud_id = ? AND documento_id = d.id) as ya_revisado,
            (SELECT comentarios FROM revisiones_aplicadas
             WHERE solicitud_id = ? AND documento_id = d.id) as ya_comentario
        FROM documentos d
        WHERE d.proyecto_id = ? AND d.activo = 1 AND d.estado != 'aprobado'
        ORDER BY d.modulo, d.codigo_completo
    """, (sol_id, sol_id, sol["proyecto_id"])).fetchall()

    return render_template("revisar.html", sol=sol, proyecto=proyecto, documentos=documentos)


@app.route("/revision/aplicar", methods=["POST"])
def aplicar_revision():
    db = get_db()
    solicitud_id = int(request.form["solicitud_id"])
    documento_id = int(request.form["documento_id"])
    resultado = request.form["resultado"]
    comentarios = request.form.get("comentarios", "").strip()

    sol = db.execute("SELECT * FROM solicitudes WHERE id = ?", (solicitud_id,)).fetchone()
    doc = db.execute("SELECT * FROM documentos WHERE id = ?", (documento_id,)).fetchone()

    # Verificar que no exista ya una revisión para este par
    existente = db.execute(
        "SELECT id FROM revisiones_aplicadas WHERE solicitud_id = ? AND documento_id = ?",
        (solicitud_id, documento_id)
    ).fetchone()

    if existente:
        # Actualizar
        db.execute(
            "UPDATE revisiones_aplicadas SET resultado = ?, comentarios = ?, fecha_revision = ? WHERE id = ?",
            (resultado, comentarios, now_chile(), existente["id"])
        )
    else:
        # Crear
        db.execute(
            "INSERT INTO revisiones_aplicadas (solicitud_id, documento_id, resultado, comentarios, fecha_revision) VALUES (?,?,?,?,?)",
            (solicitud_id, documento_id, resultado, comentarios, now_chile())
        )

    # Mutar estado del documento
    estado_anterior = doc["estado"]
    if resultado == "aprobado":
        nuevo_estado = "aprobado"
    elif resultado == "observado":
        nuevo_estado = "observado"
    elif resultado == "rechazado":
        nuevo_estado = "rechazado"
    else:
        nuevo_estado = doc["estado"]

    if nuevo_estado != estado_anterior:
        db.execute("UPDATE documentos SET estado = ? WHERE id = ?", (nuevo_estado, documento_id))

    # Historial
    desc = f"Revisión {sol['tipo']} #{sol['numero_iteracion']}: {doc['codigo_completo']} → {resultado}"
    if comentarios:
        desc += f". Nota: {comentarios}"

    db.execute(
        "INSERT INTO historial (proyecto_id, documento_id, solicitud_id, accion, valor_anterior, valor_nuevo, descripcion, fecha) VALUES (?,?,?,?,?,?,?,?)",
        (doc["proyecto_id"], documento_id, solicitud_id, "revision", estado_anterior, nuevo_estado, desc, now_chile())
    )
    db.commit()

    flash(f"{doc['codigo_completo']} marcado como {resultado}", "ok")
    return redirect(url_for("revisar_solicitud", sol_id=solicitud_id))


@app.route("/solicitud/<int:sol_id>/completar", methods=["POST"])
def completar_solicitud(sol_id):
    db = get_db()
    sol = db.execute("SELECT * FROM solicitudes WHERE id = ?", (sol_id,)).fetchone()
    if not sol:
        flash("Solicitud no encontrada", "err")
        return redirect(url_for("index"))

    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (sol["proyecto_id"],)).fetchone()

    # Verificar si quedan documentos sin revisar
    pendientes = db.execute("""
        SELECT * FROM documentos d
        WHERE d.proyecto_id = ? AND d.activo = 1 AND d.estado != 'aprobado'
        AND d.id NOT IN (
            SELECT documento_id FROM revisiones_aplicadas WHERE solicitud_id = ?
        )
    """, (sol["proyecto_id"], sol_id)).fetchall()

    revisiones = db.execute("""
        SELECT ra.*, d.codigo_completo, d.titulo 
        FROM revisiones_aplicadas ra
        JOIN documentos d ON ra.documento_id = d.id
        WHERE ra.solicitud_id = ?
    """, (sol_id,)).fetchall()

    resumen = {"aprobado": 0, "observado": 0, "rechazado": 0, "pendiente": len(pendientes)}
    for r in revisiones:
        resumen[r["resultado"]] = resumen.get(r["resultado"], 0) + 1

    if pendientes:
        flash(f"Atención: quedan {len(pendientes)} documento(s) sin revisar. Se completó igual.", "ok")
    else:
        flash("Solicitud completada", "ok")

    db.execute(
        "UPDATE solicitudes SET estado = 'completada', fecha_cierre = ? WHERE id = ?",
        (now_chile(), sol_id)
    )

    # Historial
    db.execute(
        "INSERT INTO historial (proyecto_id, solicitud_id, accion, descripcion, fecha) VALUES (?,?,?,?,?)",
        (sol["proyecto_id"], sol_id, "completar",
         f"Solicitud {sol['tipo']} #{sol['numero_iteracion']} completada", now_chile())
    )

    # Actualizar estado de flujo
    _actualizar_estado_flujo(sol["proyecto_id"], db)

    # Generar acta automática
    contenido_acta = generar_acta_md(proyecto, sol, revisiones, pendientes, resumen)
    guardar_acta(sol["proyecto_id"], sol_id, contenido_acta, db)

    flash("Acta de revisión generada automáticamente", "ok")

    return redirect(url_for("ver_solicitud", sol_id=sol_id))


@app.route("/solicitud/<int:sol_id>/cancelar", methods=["POST"])
def cancelar_solicitud(sol_id):
    db = get_db()
    sol = db.execute("SELECT * FROM solicitudes WHERE id = ?", (sol_id,)).fetchone()
    if not sol:
        flash("Solicitud no encontrada", "err")
        return redirect(url_for("index"))
    if sol["estado"] == "completada":
        flash("No se puede cancelar una solicitud ya completada", "err")
        return redirect(url_for("ver_solicitud", sol_id=sol_id))
    db.execute(
        "UPDATE solicitudes SET estado = 'cancelada', fecha_cierre = ? WHERE id = ?",
        (now_chile(), sol_id)
    )
    db.execute(
        "INSERT INTO historial (proyecto_id, solicitud_id, accion, descripcion, fecha) VALUES (?,?,?,?,?)",
        (sol["proyecto_id"], sol_id, "cancelar",
         f"Solicitud {sol['tipo']} #{sol['numero_iteracion']} cancelada", now_chile())
    )
    _actualizar_estado_flujo(sol["proyecto_id"], db)
    db.commit()
    flash(f"Solicitud {sol['tipo']} #{sol['numero_iteracion']} cancelada", "ok")
    return redirect(url_for("ver_proyecto", proyecto_id=sol["proyecto_id"]))


# ──────────────────────────────────────────────────────────────
# GENERADOR DE CORREOS TIPO
# ──────────────────────────────────────────────────────────────

def _proyecto_con_comuna(proyecto):
    """Devuelve la referencia al proyecto incluyendo comuna si existe."""
    comuna = proyecto.get("comuna")
    zona = proyecto.get("zona_sismica")
    ref = f"{proyecto['acronimo']}"
    if comuna:
        ref += f" de la comuna de {comuna}"
        if zona:
            ref += f" (Z{zona})"
    return ref


def generar_email_chk(proyecto, sol, revisiones, docs_pendientes):
    """Email para Checklist: lista documento por documento con comentarios."""
    lines = ["Estimado Coordinador,", ""]
    lines.append(f"He realizado el Checklist del proyecto {_proyecto_con_comuna(proyecto)} y el resultado arrojó lo siguiente:")
    lines.append("")

    # Separar por resultado
    aprobados = [r for r in revisiones if r["resultado"] == "aprobado"]
    observados = [r for r in revisiones if r["resultado"] == "observado"]
    rechazados = [r for r in revisiones if r["resultado"] == "rechazado"]

    if observados:
        lines.append("Documentos observados:")
        for r in observados:
            comentario = r["comentarios"] or "Sin comentarios"
            lines.append(f"- {r['codigo_completo']}: {comentario}")
        lines.append("")

    if rechazados:
        lines.append("Documentos rechazados:")
        for r in rechazados:
            comentario = r["comentarios"] or "Sin comentarios"
            lines.append(f"- {r['codigo_completo']}: {comentario}")
        lines.append("")

    if docs_pendientes:
        lines.append("Documentos faltantes:")
        for d in docs_pendientes:
            lines.append(f"- {d['codigo_completo']} ({d['titulo']})")
        lines.append("")

    if aprobados:
        lines.append("Documentos aprobados:")
        for r in aprobados:
            lines.append(f"- {r['codigo_completo']}")
        lines.append("")

    lines.append("Se solicita corregir los documentos observados y presentarlos en la próxima iteración de Checklist.")
    lines.append("")
    lines.append("Saludos,")
    lines.append("")
    lines.append("[Tu nombre]")
    lines.append("[Cargo]")
    lines.append("[Empresa]")

    return "\n".join(lines)


def generar_email_r01_r02(proyecto, sol, resumen):
    """Email para R01/R02: resumen numérico + referencia a acta adjunta."""
    lines = ["Estimado Coordinador,", ""]
    lines.append(f"He realizado la {sol['tipo']} del proyecto {_proyecto_con_comuna(proyecto)}. El resultado arrojó lo siguiente:")
    lines.append("")
    lines.append(f"- {resumen.get('aprobado', 0)} documento(s) aprobado(s)")
    lines.append(f"- {resumen.get('observado', 0)} documento(s) observado(s)")
    lines.append(f"- {resumen.get('rechazado', 0)} documento(s) rechazado(s)")
    lines.append(f"- {resumen.get('pendiente', 0)} documento(s) pendiente(s) de revisión")
    lines.append("")
    lines.append("Adjunto acta de revisión con el detalle específico de cada documento.")
    lines.append("")
    lines.append("Saludos,")
    lines.append("")
    lines.append("[Tu nombre]")
    lines.append("[Cargo]")
    lines.append("[Empresa]")

    return "\n".join(lines)


def generar_email_rex(proyecto, sol, revisiones, motivo_rechazo=""):
    """Email para REX: lista de rechazados + comentarios + motivo de rechazo del proyecto."""
    lines = ["Estimado Coordinador,", ""]
    lines.append(f"He realizado la Revisión Excepcional del proyecto {_proyecto_con_comuna(proyecto)}. El resultado arrojó lo siguiente:")
    lines.append("")

    rechazados = [r for r in revisiones if r["resultado"] == "rechazado"]

    if rechazados:
        lines.append("Documentos rechazados:")
        for r in rechazados:
            comentario = r["comentarios"] or "Sin comentarios"
            lines.append(f"- {r['codigo_completo']}: {comentario}")
        lines.append("")

    if motivo_rechazo:
        lines.append("Motivo de rechazo del proyecto:")
        lines.append(motivo_rechazo)
        lines.append("")
    else:
        lines.append("Motivo de rechazo del proyecto:")
        lines.append("[Indicar motivo de rechazo del proyecto]")
        lines.append("")

    lines.append("Saludos,")
    lines.append("")
    lines.append("[Tu nombre]")
    lines.append("[Cargo]")
    lines.append("[Empresa]")

    return "\n".join(lines)


# Diccionario extensible de generadores de correo
EMAIL_GENERATORS = {
    "CHK": generar_email_chk,
    "R01": generar_email_r01_r02,
    "R02": generar_email_r01_r02,
    "REX": generar_email_rex,
}


@app.route("/solicitud/<int:sol_id>/email")
def generar_email(sol_id):
    db = get_db()
    sol = db.execute("SELECT * FROM solicitudes WHERE id = ?", (sol_id,)).fetchone()
    if not sol:
        flash("Solicitud no encontrada", "err")
        return redirect(url_for("index"))

    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (sol["proyecto_id"],)).fetchone()

    # Revisiones aplicadas en esta solicitud
    revisiones = db.execute("""
        SELECT ra.*, d.codigo_completo, d.titulo, d.estado as doc_estado
        FROM revisiones_aplicadas ra
        JOIN documentos d ON ra.documento_id = d.id
        WHERE ra.solicitud_id = ?
        ORDER BY d.codigo_completo
    """, (sol_id,)).fetchall()

    # Documentos pendientes de revisión
    docs_pendientes = db.execute("""
        SELECT d.* FROM documentos d
        WHERE d.proyecto_id = ? AND d.activo = 1 AND d.estado != 'aprobado'
        AND d.id NOT IN (
            SELECT documento_id FROM revisiones_aplicadas WHERE solicitud_id = ?
        )
        ORDER BY d.codigo_completo
    """, (sol["proyecto_id"], sol_id)).fetchall()

    # Resumen
    resumen = {"aprobado": 0, "observado": 0, "rechazado": 0, "pendiente": len(docs_pendientes)}
    for r in revisiones:
        if r["resultado"] in resumen:
            resumen[r["resultado"]] = resumen.get(r["resultado"], 0) + 1

    tipo = sol["tipo"]
    generator = EMAIL_GENERATORS.get(tipo)

    if not generator:
        flash(f"No hay template de correo para solicitudes tipo {tipo}", "err")
        return redirect(url_for("ver_solicitud", sol_id=sol_id))

    # Generar contenido según tipo
    if tipo == "CHK":
        contenido = generator(proyecto, sol, revisiones, docs_pendientes)
    elif tipo in ("R01", "R02"):
        contenido = generator(proyecto, sol, resumen)
    elif tipo == "REX":
        # Para REX, usar motivo de cierre del proyecto si existe
        motivo = proyecto.get("motivo_cierre") or ""
        contenido = generator(proyecto, sol, revisiones, motivo)
    else:
        contenido = generator(proyecto, sol, revisiones, docs_pendientes)

    # Descargar como .txt
    filename = f"email_{proyecto['acronimo']}_{tipo}{sol['numero_iteracion']}.txt"
    buffer = io.BytesIO(contenido.encode("utf-8"))
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="text/plain",
        as_attachment=True,
        download_name=filename
    )


# ──────────────────────────────────────────────────────────────
# FASE 5 - REPORTES Y REPOSITORIO
# ──────────────────────────────────────────────────────────────

@app.route("/proyecto/<int:proyecto_id>/reporte/md")
def reporte_md(proyecto_id):
    db = get_db()
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
    if not proyecto:
        flash("Proyecto no encontrado", "err")
        return redirect(url_for("index"))

    documentos = db.execute(
        "SELECT * FROM documentos WHERE proyecto_id = ? AND activo = 1 ORDER BY codigo_completo",
        (proyecto_id,)
    ).fetchall()

    eliminados = db.execute(
        "SELECT * FROM documentos_eliminados WHERE proyecto_id = ? ORDER BY fecha_eliminacion DESC",
        (proyecto_id,)
    ).fetchall()

    solicitudes = db.execute(
        "SELECT * FROM solicitudes WHERE proyecto_id = ? ORDER BY fecha_entrada DESC",
        (proyecto_id,)
    ).fetchall()

    historial = db.execute("""
        SELECT h.*, d.codigo_completo as doc_codigo
        FROM historial h
        LEFT JOIN documentos d ON h.documento_id = d.id
        WHERE h.proyecto_id = ?
        ORDER BY h.fecha DESC
    """, (proyecto_id,)).fetchall()

    md = f"""# Reporte de Trazabilidad: {proyecto['acronimo']} - {proyecto['nombre']}

## Información General
- **Acrónimo:** {proyecto['acronimo']}
- **Nombre:** {proyecto['nombre']}
- **Estado:** {proyecto['estado_global'].upper()}
- **Carpeta raíz:** `{proyecto['carpeta_raiz']}`
- **Fecha creación:** {proyecto['fecha_creacion']}
"""
    if proyecto['fecha_cierre']:
        md += f"- **Fecha cierre:** {proyecto['fecha_cierre']}\n"
    if proyecto['motivo_cierre']:
        md += f"- **Motivo cierre:** {proyecto['motivo_cierre']}\n"
    if proyecto['notas']:
        md += f"- **Notas:** {proyecto['notas']}\n"

    md += "\n## Documentos Registrados\n\n"
    if documentos:
        md += "| Código | Título | Estado | Ruta física | Registrado |\n"
        md += "|--------|--------|--------|-------------|------------|\n"
        for d in documentos:
            ruta = d['ruta_fisica'] or '-'
            md += f"| {d['codigo_completo']} | {d['titulo']} | {d['estado']} | `{ruta}` | {d['fecha_registro'][:10]} |\n"
    else:
        md += "No hay documentos registrados.\n"

    estados = {}
    for d in documentos:
        estados[d['estado']] = estados.get(d['estado'], 0) + 1

    md += "\n## Resumen de Estados\n"
    for estado, count in sorted(estados.items()):
        md += f"- **{estado.capitalize()}:** {count}\n"
    md += f"- **Total documentos activos:** {len(documentos)}\n"

    md += "\n## Solicitudes\n\n"
    if solicitudes:
        md += "| Tipo | Iteración | Fecha entrada | Fecha límite | Estado | Fecha cierre |\n"
        md += "|------|-----------|---------------|--------------|--------|--------------|\n"
        for s in solicitudes:
            limite = s['fecha_limite'] or '-'
            cierre = s['fecha_cierre'] or '-'
            md += f"| {s['tipo']} | #{s['numero_iteracion']} | {s['fecha_entrada']} | {limite} | {s['estado']} | {cierre} |\n"
    else:
        md += "No hay solicitudes registradas.\n"

    md += "\n## Documentos Eliminados (Cementerio)\n\n"
    if eliminados:
        md += "| Código | Título | Razón eliminación | Fecha |\n"
        md += "|--------|--------|-------------------|-------|\n"
        for e in eliminados:
            md += f"| {e['codigo_completo']} | {e['titulo']} | {e['razon_eliminacion']} | {e['fecha_eliminacion'][:10]} |\n"
    else:
        md += "No hay documentos eliminados.\n"

    md += "\n## Historial Completo\n\n"
    if historial:
        md += "| Fecha | Acción | Descripción |\n"
        md += "|-------|--------|-------------|\n"
        for h in historial:
            md += f"| {h['fecha']} | {h['accion']} | {h['descripcion']} |\n"
    else:
        md += "No hay registros de historial.\n"

    md += f"\n---\n*Reporte generado el {now_chile()}*\n"

    buffer = io.BytesIO(md.encode('utf-8'))
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='text/markdown',
        as_attachment=True,
        download_name=f"trazabilidad_{proyecto['acronimo']}.md"
    )


@app.route("/proyecto/<int:proyecto_id>/reporte/pdf")
def reporte_pdf(proyecto_id):
    db = get_db()
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
    if not proyecto:
        flash("Proyecto no encontrado", "err")
        return redirect(url_for("index"))

    documentos = db.execute(
        "SELECT * FROM documentos WHERE proyecto_id = ? AND activo = 1 ORDER BY codigo_completo",
        (proyecto_id,)
    ).fetchall()

    solicitudes = db.execute(
        "SELECT * FROM solicitudes WHERE proyecto_id = ? ORDER BY fecha_entrada DESC",
        (proyecto_id,)
    ).fetchall()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Encabezado
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, ascii_safe("Reporte de Trazabilidad"), ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, ascii_safe(f"Generado: {now_chile()}"), ln=True, align="C")
    pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
    pdf.ln(6)

    # Info del proyecto
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, ascii_safe(f"{proyecto['acronimo']} - {proyecto['nombre']}"), ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, ascii_safe(f"Estado: {proyecto['estado_global'].upper()}"), ln=True)
    pdf.cell(0, 6, ascii_safe(f"Carpeta: {proyecto['carpeta_raiz']}"), ln=True)
    if proyecto['fecha_cierre']:
        pdf.cell(0, 6, ascii_safe(f"Cierre: {proyecto['fecha_cierre']}"), ln=True)
    pdf.ln(4)

    # Resumen en caja
    estados = {}
    for d in documentos:
        estados[d['estado']] = estados.get(d['estado'], 0) + 1

    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, ascii_safe(" Resumen del Proyecto"), ln=True, fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, ascii_safe(f"   Documentos registrados: {len(documentos)}"), ln=True)
    for estado, count in sorted(estados.items()):
        pdf.cell(0, 6, ascii_safe(f"   {estado.capitalize()}: {count}"), ln=True)
    pdf.cell(0, 6, ascii_safe(f"   Solicitudes: {len(solicitudes)}"), ln=True)
    pdf.ln(4)

    # Tabla de documentos
    if documentos:
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, ascii_safe(" Documentos"), ln=True, fill=True)
        pdf.set_font("Helvetica", "", 8)

        # Header
        pdf.set_fill_color(210, 210, 210)
        pdf.cell(55, 7, ascii_safe("Codigo"), 1, 0, "C", True)
        pdf.cell(28, 7, ascii_safe("Estado"), 1, 0, "C", True)
        pdf.cell(70, 7, ascii_safe("Titulo"), 1, 0, "C", True)
        pdf.cell(37, 7, ascii_safe("Registrado"), 1, 1, "C", True)

        pdf.set_fill_color(255, 255, 255)
        for d in documentos:
            pdf.cell(55, 6, ascii_safe(d['codigo_completo']), 1)
            pdf.cell(28, 6, ascii_safe(d['estado']), 1, 0, "C")
            titulo = d['titulo'][:32] + "..." if len(d['titulo']) > 35 else d['titulo']
            pdf.cell(70, 6, ascii_safe(titulo), 1)
            pdf.cell(37, 6, ascii_safe(d['fecha_registro'][:10]), 1, 0, "C")
            pdf.ln()
        pdf.ln(4)

    # Solicitudes
    if solicitudes:
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, ascii_safe(" Solicitudes"), ln=True, fill=True)
        pdf.set_font("Helvetica", "", 8)

        pdf.set_fill_color(210, 210, 210)
        pdf.cell(30, 7, ascii_safe("Tipo"), 1, 0, "C", True)
        pdf.cell(22, 7, ascii_safe("Iter"), 1, 0, "C", True)
        pdf.cell(40, 7, ascii_safe("Entrada"), 1, 0, "C", True)
        pdf.cell(40, 7, ascii_safe("Estado"), 1, 0, "C", True)
        pdf.cell(58, 7, ascii_safe("Cierre"), 1, 1, "C", True)

        pdf.set_fill_color(255, 255, 255)
        for s in solicitudes:
            pdf.cell(30, 6, ascii_safe(s['tipo']), 1, 0, "C")
            pdf.cell(22, 6, ascii_safe(f"#{s['numero_iteracion']}"), 1, 0, "C")
            pdf.cell(40, 6, ascii_safe(s['fecha_entrada'][:10]), 1, 0, "C")
            pdf.cell(40, 6, ascii_safe(s['estado']), 1, 0, "C")
            cierre = s['fecha_cierre'][:10] if s['fecha_cierre'] else "-"
            pdf.cell(58, 6, ascii_safe(cierre), 1, 0, "C")
            pdf.ln()

    # Pie de pagina
    pdf.set_y(-20)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(128, 128, 128)
    pdf.cell(0, 5, ascii_safe(f"Documento generado automaticamente - Plataforma de Ingenieria - {now_chile()[:10]}"), 0, 0, "C")

    buffer = io.BytesIO()
    pdf.output(buffer)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=ascii_safe(f"trazabilidad_{proyecto['acronimo']}.pdf")
    )


@app.route("/reporte/global/md")
def reporte_global_md():
    db = get_db()
    proyectos = db.execute("""
        SELECT p.*, s.tipo as sol_tipo, s.numero_iteracion as sol_iter
        FROM proyectos p
        LEFT JOIN solicitudes s ON p.id = s.proyecto_id AND s.estado != 'completada'
        WHERE p.estado_global = 'activo'
        ORDER BY p.fecha_creacion DESC
    """).fetchall()

    md = """# Reporte Global - Proyectos Activos

| Acrónimo | Nombre | Solicitud Activa | Creado | Docs | Aprobados | Observados | Rechazados |
|----------|--------|------------------|--------|------|-----------|------------|------------|
"""

    for p in proyectos:
        counts = db.execute(
            "SELECT estado, COUNT(*) as c FROM documentos WHERE proyecto_id = ? AND activo = 1 GROUP BY estado",
            (p['id'],)
        ).fetchall()
        estados = {c['estado']: c['c'] for c in counts}
        total = sum(estados.values())
        sol = f"{p['sol_tipo']}#{p['sol_iter']}" if p['sol_tipo'] else "Sin solicitud"
        md += f"| {p['acronimo']} | {p['nombre']} | {sol} | {p['fecha_creacion'][:10]} | {total} | {estados.get('aprobado', 0)} | {estados.get('observado', 0)} | {estados.get('rechazado', 0)} |\n"

    md += f"\n**Total proyectos activos:** {len(proyectos)}\n"
    md += f"\n---\n*Reporte generado el {now_chile()}*\n"

    buffer = io.BytesIO(md.encode('utf-8'))
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='text/markdown',
        as_attachment=True,
        download_name=f"reporte_global_{now_chile()[:10]}.md"
    )




@app.route("/exportar/proyectos/csv")
def exportar_proyectos_csv():
    """Exporta proyectos activos a CSV con conteo de documentos por estado."""
    db = get_db()
    proyectos = db.execute(
        "SELECT * FROM proyectos WHERE estado_global = 'activo' ORDER BY fecha_creacion DESC"
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "acronimo", "nombre", "estado_global", "carpeta_raiz",
                       "comuna", "zona_sismica", "fecha_creacion",
                       "total_docs", "aprobados", "observados", "rechazados", "pendientes"])

    for p in proyectos:
        counts = db.execute(
            "SELECT estado, COUNT(*) as c FROM documentos WHERE proyecto_id = ? AND activo = 1 GROUP BY estado",
            (p["id"],)
        ).fetchall()
        estados = {c["estado"]: c["c"] for c in counts}
        total = sum(estados.values())
        writer.writerow([
            p["id"], p["acronimo"], p["nombre"], p["estado_global"], p["carpeta_raiz"] or "",
            p["comuna"] or "", p["zona_sismica"] or "", p["fecha_creacion"][:10] if p["fecha_creacion"] else "",
            total, estados.get("aprobado", 0), estados.get("observado", 0),
            estados.get("rechazado", 0), estados.get("pendiente", 0)
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    output.close()
    buffer = io.BytesIO(csv_bytes)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="text/csv; charset=utf-8-sig",
        as_attachment=True,
        download_name=f"proyectos_{now_chile()[:10]}.csv"
    )
@app.route("/proyecto/<int:proyecto_id>/repositorio/md")
def repositorio_md(proyecto_id):
    db = get_db()
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
    if not proyecto:
        flash("Proyecto no encontrado", "err")
        return redirect(url_for("index"))

    documentos = db.execute(
        "SELECT * FROM documentos WHERE proyecto_id = ? AND activo = 1 ORDER BY modulo, codigo_completo",
        (proyecto_id,)
    ).fetchall()

    md = f"""# Repositorio Digital: {proyecto['acronimo']} - {proyecto['nombre']}

> Mapa de documentos registrados en la plataforma.
> **Carpeta raíz:** `{proyecto['carpeta_raiz']}`
> **Generado:** {now_chile()}

## Índice de Documentos

| Código | Módulo | Tipo | Familia | Elemento | Versión | Título | Estado | Ubicación Física |
|--------|--------|------|---------|----------|---------|--------|--------|------------------|
"""

    for d in documentos:
        ruta = d['ruta_fisica'] or '-'
        md += f"| {d['codigo_completo']} | {d['modulo']} | {d['tipo_documento']} | {d['familia']} | {d['elemento']} | {d['version']} | {d['titulo']} | {d['estado']} | `{ruta}` |\n"

    md += f"\n**Total documentos:** {len(documentos)}\n"
    md += f"\n---\n*Repositorio generado automáticamente desde la plataforma*\n"

    buffer = io.BytesIO(md.encode('utf-8'))
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='text/markdown',
        as_attachment=True,
        download_name=f"repositorio_{proyecto['acronimo']}.md"
    )


# ──────────────────────────────────────────────────────────────
# BACKUP
# ──────────────────────────────────────────────────────────────
@app.route("/backup")
def backup():
    """Genera un ZIP con la base de datos para descargar."""
    if not DATABASE.exists():
        flash("No hay base de datos para respaldar", "err")
        return redirect(url_for("index"))

    timestamp = now_chile().replace(" ", "_").replace(":", "-")
    zip_name = f"backup_proyectos_{timestamp}.zip"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(DATABASE, arcname="proyectos.db")
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=zip_name
    )


# ──────────────────────────────────────────────────────────────
# TAREAS ( independientes de proyectos )
# ──────────────────────────────────────────────────────────────

@app.route("/tareas", methods=["GET", "POST"])
def tareas():
    db = get_db()
    filtro = request.args.get("filtro", "todas")

    if request.method == "POST":
        asunto = request.form["asunto"].strip()
        fecha_solicitud = request.form["fecha_solicitud"]
        fecha_limite = request.form.get("fecha_limite") or None
        notas = request.form.get("notas", "").strip()
        db.execute(
            "INSERT INTO tareas (asunto, fecha_solicitud, fecha_limite, estado, notas) VALUES (?,?,?,?,?)",
            (asunto, fecha_solicitud, fecha_limite, "pendiente", notas)
        )
        db.commit()
        flash("Tarea creada", "ok")
        return redirect(url_for("tareas", filtro=filtro))

    sql = "SELECT * FROM tareas"
    if filtro == "pendientes":
        sql += " WHERE estado IN ('pendiente', 'en_progreso')"
    elif filtro == "completadas":
        sql += " WHERE estado = 'completada'"
    sql += " ORDER BY CASE estado WHEN 'pendiente' THEN 1 WHEN 'en_progreso' THEN 2 ELSE 3 END, fecha_limite ASC, fecha_solicitud DESC"
    lista = db.execute(sql).fetchall()
    hoy = now_chile()[:10]
    return render_template("tareas.html", tareas=lista, filtro=filtro, hoy=hoy)


@app.route("/tarea/<int:tarea_id>/estado", methods=["POST"])
def cambiar_estado_tarea(tarea_id):
    db = get_db()
    estado = request.form["estado"]
    if estado == "completada":
        db.execute(
            "UPDATE tareas SET estado = ?, fecha_completada = ? WHERE id = ?",
            (estado, now_chile(), tarea_id)
        )
    else:
        db.execute(
            "UPDATE tareas SET estado = ?, fecha_completada = NULL WHERE id = ?",
            (estado, tarea_id)
        )
    db.commit()
    flash("Estado actualizado", "ok")
    return redirect(url_for("tareas"))


@app.route("/tarea/<int:tarea_id>/eliminar", methods=["POST"])
def eliminar_tarea(tarea_id):
    db = get_db()
    db.execute("DELETE FROM tareas WHERE id = ?", (tarea_id,))
    db.commit()
    flash("Tarea eliminada", "ok")
    return redirect(url_for("tareas"))


@app.route("/tarea/<int:tarea_id>/editar", methods=["GET", "POST"])
def editar_tarea(tarea_id):
    db = get_db()
    tarea = db.execute("SELECT * FROM tareas WHERE id = ?", (tarea_id,)).fetchone()
    if not tarea:
        flash("Tarea no encontrada", "err")
        return redirect(url_for("tareas"))
    if request.method == "POST":
        asunto = request.form["asunto"].strip()
        fecha_solicitud = request.form["fecha_solicitud"]
        fecha_limite = request.form.get("fecha_limite") or None
        notas = request.form.get("notas", "").strip()
        db.execute(
            "UPDATE tareas SET asunto = ?, fecha_solicitud = ?, fecha_limite = ?, notas = ? WHERE id = ?",
            (asunto, fecha_solicitud, fecha_limite, notas, tarea_id)
        )
        db.commit()
        flash("Tarea actualizada", "ok")
        return redirect(url_for("tareas"))
    return render_template("editar_tarea.html", tarea=tarea)


# ──────────────────────────────────────────────────────────────
# JORNADA LABORAL
# ──────────────────────────────────────────────────────────────

def _rango_semana(fecha_ref=None):
    """Devuelve lunes y domingo de la semana de fecha_ref (default hoy)."""
    if fecha_ref is None:
        fecha_ref = datetime.now(TZ_CHILE).date()
    lunes = fecha_ref - timedelta(days=fecha_ref.weekday())
    domingo = lunes + timedelta(days=6)
    return lunes, domingo


@app.route("/jornada")
def jornada():
    db = get_db()
    semana_offset = int(request.args.get("semana", 0))
    hoy = datetime.now(TZ_CHILE).date()
    lunes_ref = hoy + timedelta(weeks=semana_offset)
    lunes, domingo = _rango_semana(lunes_ref)

    # Traer registros de esta semana
    registros_raw = db.execute(
        "SELECT * FROM jornada WHERE fecha >= ? AND fecha <= ? ORDER BY fecha",
        (lunes.isoformat(), domingo.isoformat())
    ).fetchall()
    registros = {r["fecha"]: r for r in registros_raw}

    # Construir días
    dias = []
    nombres = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    for i in range(7):
        fecha = lunes + timedelta(days=i)
        r = registros.get(fecha.isoformat())
        horas = ""
        if r and r["entrada"] and r["salida"]:
            try:
                e = datetime.strptime(r["entrada"], "%H:%M")
                s = datetime.strptime(r["salida"], "%H:%M")
                diff = s - e
                horas = f"{diff.seconds // 3600}h {(diff.seconds % 3600) // 60:02d}m"
            except Exception:
                horas = ""
        dias.append({
            "nombre": nombres[i],
            "fecha": fecha,
            "fecha_str": fecha.isoformat(),
            "registro": r,
            "horas": horas,
            "es_hoy": fecha == hoy,
        })

    # Totales solo días hábiles (lun-vie)
    total_seg = 0
    for d in dias[:5]:
        r = d["registro"]
        if r and r["entrada"] and r["salida"]:
            try:
                e = datetime.strptime(r["entrada"], "%H:%M")
                s = datetime.strptime(r["salida"], "%H:%M")
                total_seg += (s - e).seconds
            except Exception:
                pass
    total_horas = f"{total_seg // 3600}h {(total_seg % 3600) // 60:02d}m"

    es_lunes_hoy = hoy.weekday() == 0
    return render_template("jornada.html", dias=dias, total_horas=total_horas,
                           lunes=lunes, domingo=domingo, semana_offset=semana_offset,
                           es_lunes_hoy=es_lunes_hoy, hoy=hoy.isoformat())


@app.route("/buscar")
def buscar():
    db = get_db()
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        flash("Ingresa al menos 2 caracteres para buscar", "err")
        return redirect(url_for("index"))
    like = f"%{q}%"
    proyectos = db.execute(
        "SELECT * FROM proyectos WHERE acronimo LIKE ? OR nombre LIKE ? OR comuna LIKE ? ORDER BY fecha_creacion DESC LIMIT 20",
        (like, like, like)
    ).fetchall()
    documentos = db.execute(
        """SELECT d.*, p.acronimo, p.nombre as proyecto_nombre, p.id as proyecto_id
        FROM documentos d
        JOIN proyectos p ON d.proyecto_id = p.id
        WHERE d.activo = 1 AND (d.codigo_completo LIKE ? OR d.titulo LIKE ?)
        ORDER BY d.codigo_completo LIMIT 30""",
        (like, like)
    ).fetchall()
    tareas = db.execute(
        "SELECT * FROM tareas WHERE asunto LIKE ? OR notas LIKE ? ORDER BY fecha_creacion DESC LIMIT 20",
        (like, like)
    ).fetchall()
    return render_template("buscar.html", q=q, proyectos=proyectos, documentos=documentos, tareas=tareas)


@app.route("/jornada/fichar", methods=["POST"])
def fichar_jornada():
    db = get_db()
    fecha = request.form["fecha"]
    accion = request.form["accion"]

    reg = db.execute("SELECT * FROM jornada WHERE fecha = ?", (fecha,)).fetchone()

    if accion == "entrada":
        hora = now_chile()[11:16]  # HH:MM
        if reg:
            db.execute("UPDATE jornada SET entrada = ?, estado = 'trabajado' WHERE fecha = ?",
                       (hora, fecha))
        else:
            db.execute("INSERT INTO jornada (fecha, entrada, estado) VALUES (?,?,?)",
                       (fecha, hora, "trabajado"))
        flash(f"Entrada registrada: {hora}", "ok")

    elif accion == "salida":
        hora = now_chile()[11:16]
        if reg:
            db.execute("UPDATE jornada SET salida = ?, estado = 'trabajado' WHERE fecha = ?",
                       (hora, fecha))
            flash(f"Salida registrada: {hora}", "ok")
        else:
            flash("No hay entrada registrada para este día", "err")

    elif accion in ("feriado", "permiso"):
        if reg:
            db.execute("UPDATE jornada SET estado = ?, entrada = NULL, salida = NULL WHERE fecha = ?",
                       (accion, fecha))
        else:
            db.execute("INSERT INTO jornada (fecha, estado) VALUES (?,?)",
                       (fecha, accion))
        flash(f"Día marcado como {accion}", "ok")

    elif accion == "trabajar":
        if reg:
            db.execute("UPDATE jornada SET estado = 'trabajado', entrada = NULL, salida = NULL WHERE fecha = ?",
                       (fecha,))
        else:
            db.execute("INSERT INTO jornada (fecha, estado) VALUES (?,?)",
                       (fecha, "trabajado"))
        flash(f"Día marcado como trabajado. Ahora puedes fichar entrada/salida.", "ok")

    db.commit()
    return redirect(url_for("jornada"))


@app.route("/jornada/editar", methods=["POST"])
def editar_jornada():
    db = get_db()
    fecha = request.form["fecha"]
    entrada = request.form.get("entrada", "").strip()
    salida = request.form.get("salida", "").strip()
    reg = db.execute("SELECT * FROM jornada WHERE fecha = ?", (fecha,)).fetchone()
    if reg:
        db.execute(
            "UPDATE jornada SET entrada = ?, salida = ?, estado = 'trabajado' WHERE fecha = ?",
            (entrada or None, salida or None, fecha)
        )
    else:
        db.execute(
            "INSERT INTO jornada (fecha, entrada, salida, estado) VALUES (?,?,?,?)",
            (fecha, entrada or None, salida or None, "trabajado")
        )
    db.commit()
    flash("Horas actualizadas", "ok")
    return redirect(url_for("jornada"))


# ──────────────────────────────────────────────────────────────
# REPORTE SEMANAL
# ──────────────────────────────────────────────────────────────

@app.route("/reporte/semanal")
def reporte_semanal():
    return render_template("reporte_semanal.html")


@app.route("/reporte/semanal/generar")
def generar_reporte_semanal():
    db = get_db()
    hoy = datetime.now(TZ_CHILE).date()
    # Semana anterior (lunes a viernes)
    lunes = hoy - timedelta(days=hoy.weekday() + 7)
    viernes = lunes + timedelta(days=4)

    # Jornada
    jornada_raw = db.execute(
        "SELECT * FROM jornada WHERE fecha >= ? AND fecha <= ? ORDER BY fecha",
        (lunes.isoformat(), viernes.isoformat())
    ).fetchall()

    # Tareas completadas esa semana
    tareas_raw = db.execute(
        """SELECT * FROM tareas
           WHERE estado = 'completada'
           AND date(fecha_completada) >= ? AND date(fecha_completada) <= ?
           ORDER BY fecha_completada""",
        (lunes.isoformat(), viernes.isoformat())
    ).fetchall()

    # Solicitudes completadas esa semana
    solicitudes_raw = db.execute(
        """SELECT s.*, p.acronimo, p.nombre as proyecto_nombre
           FROM solicitudes s
           JOIN proyectos p ON s.proyecto_id = p.id
           WHERE s.estado = 'completada'
           AND date(s.fecha_cierre) >= ? AND date(s.fecha_cierre) <= ?
           ORDER BY s.fecha_cierre""",
        (lunes.isoformat(), viernes.isoformat())
    ).fetchall()

    nombres_dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
    lines = []
    lines.append("REPORTE SEMANAL DE ACTIVIDADES")
    lines.append(f"Semana del {lunes.strftime('%d/%m/%Y')} al {viernes.strftime('%d/%m/%Y')}")
    lines.append("")

    # Jornada
    lines.append("JORNADA LABORAL:")
    jornada_dict = {r["fecha"]: r for r in jornada_raw}
    total_seg = 0
    for i, nombre in enumerate(nombres_dias):
        fecha = lunes + timedelta(days=i)
        fecha_str = fecha.strftime("%d/%m/%Y")
        r = jornada_dict.get(fecha.isoformat())
        if r:
            if r["estado"] == "feriado":
                lines.append(f"{nombre} {fecha_str}: Feriado")
            elif r["estado"] == "permiso":
                lines.append(f"{nombre} {fecha_str}: Permiso administrativo")
            elif r["entrada"] and r["salida"]:
                e = datetime.strptime(r["entrada"], "%H:%M")
                s = datetime.strptime(r["salida"], "%H:%M")
                diff = s - e
                total_seg += diff.seconds
                lines.append(f"{nombre} {fecha_str}: {r['entrada']} - {r['salida']} ({diff.seconds // 3600}h {(diff.seconds % 3600) // 60:02d}m)")
            elif r["entrada"]:
                lines.append(f"{nombre} {fecha_str}: {r['entrada']} - [Sin salida]")
            else:
                lines.append(f"{nombre} {fecha_str}: Sin registro")
        else:
            lines.append(f"{nombre} {fecha_str}: Sin registro")
    lines.append("")
    lines.append(f"Total horas trabajadas: {total_seg // 3600}h {(total_seg % 3600) // 60:02d}m")
    lines.append("")

    # Tareas
    lines.append("TAREAS COMPLETADAS:")
    if tareas_raw:
        for t in tareas_raw:
            fc = t["fecha_completada"][:10] if t["fecha_completada"] else ""
            lines.append(f"✓ {t['asunto']} ({fc})")
    else:
        lines.append("No hay tareas completadas esta semana.")
    lines.append("")

    # Proyectos revisados
    lines.append("PROYECTOS REVISADOS:")
    if solicitudes_raw:
        for s in solicitudes_raw:
            lines.append(f"• {s['acronimo']}: {s['tipo']} completada ({s['fecha_cierre'][:10]})")
    else:
        lines.append("No hay revisiones completadas esta semana.")
    lines.append("")

    lines.append("Saludos,")
    lines.append("")
    lines.append(USER_NAME)

    contenido = "\n".join(lines)
    filename = f"reporte_semanal_{lunes.strftime('%Y%m%d')}.txt"
    buffer = io.BytesIO(contenido.encode("utf-8"))
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="text/plain",
        as_attachment=True,
        download_name=filename
    )


# ──────────────────────────────────────────────────────────────
# MANEJO DE ERRORES
# ──────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template("500.html"), 500


# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not DATABASE.exists():
        init_db()
    else:
        migrate_db()
    app.run(debug=False, host="127.0.0.1", port=5000)