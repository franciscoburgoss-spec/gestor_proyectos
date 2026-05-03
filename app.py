# -*- coding: utf-8 -*-
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, g, send_file
import io
from fpdf import FPDF
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import zipfile
import json

TZ_CHILE = ZoneInfo("America/Santiago")

def now_chile():
    """Devuelve fecha/hora actual en Chile como string YYYY-MM-DD HH:MM:SS."""
    return datetime.now(TZ_CHILE).strftime("%Y-%m-%d %H:%M:%S")


def dias_habiles(fecha_inicio, fecha_fin):
    """Cuenta días hábiles entre dos fechas (inclusive), excluyendo sábados y domingos."""
    if fecha_fin < fecha_inicio:
        return -1
    dias = 0
    current = fecha_inicio
    while current <= fecha_fin:
        if current.weekday() < 5:
            dias += 1
        current += timedelta(days=1)
    return dias


def ascii_safe(text):
    """Convierte texto a ASCII basico para compatibilidad con fuentes core de FPDF2."""
    if text is None:
        return ""
    t = str(text)
    # Em-dash / en-dash a guion simple
    t = t.replace("\u2014", "-").replace("\u2013", "-")
    # Comillas tipograficas a simples
    t = t.replace("\u2018", "'").replace("\u2019", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    # Tildes y acentos
    trans = str.maketrans(
        "áéíóúÁÉÍÓÚñÑüÜ¿¡",
        "aeiouAEIOUnNuU?!"
    )
    return t.translate(trans)


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

DATABASE = BASE_DIR / "data" / "proyectos.db"
SCHEMA = BASE_DIR / "schema.sql"

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(str(DATABASE))
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

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

    return render_template("index.html", proyectos=proyectos, cerrados=cerrados, pendientes=pendientes, hoy=now_chile()[:10], filtro=filtro, comunas=COMUNAS)

@app.route("/proyecto/crear", methods=["POST"])
def crear_proyecto():
    db = get_db()
    acronimo = request.form["acronimo"].strip().upper()
    nombre = request.form["nombre"].strip()
    carpeta = request.form["carpeta_raiz"].strip()
    comuna = request.form.get("comuna", "").strip()
    zona = request.form.get("zona_sismica", "").strip()
    notas = request.form.get("notas", "").strip()
    num_tipologias = request.form.get("num_tipologias", "0").strip()

    # Zona sísmica: prioridad al input directo, fallback a comunas.json
    zona_sismica = None
    if zona:
        try:
            zona_sismica = int(zona)
        except ValueError:
            zona_sismica = None
    if zona_sismica is None and comuna:
        zona_sismica = ZONAS.get(comuna, None)

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

        # 2. Elemento PRO (General) siempre presente
        db.execute(
            "INSERT INTO elementos_proyecto (proyecto_id, codigo, nombre, familia, orden) VALUES (?,?,?,?,?)",
            (pid, "PRO", "Proyecto General", "GEN", 999)
        )

        # 3. Elementos complementarios opcionales
        # Formato: nombre:código  o  nombre:código:familia
        # Familia por defecto: OBR
        extras = request.form.get("elementos_extra", "").strip()
        if extras:
            for item in extras.split(","):
                item = item.strip()
                if ":" in item:
                    partes = item.split(":")
                    nombre_elem = partes[0].strip()
                    codigo_elem = partes[1].strip().upper()
                    familia_elem = partes[2].strip().upper() if len(partes) > 2 else "OBR"
                    if nombre_elem and codigo_elem:
                        db.execute(
                            "INSERT INTO elementos_proyecto (proyecto_id, codigo, nombre, familia, orden) VALUES (?,?,?,?,?)",
                            (pid, codigo_elem, nombre_elem, familia_elem, 100)
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
        zona_raw = request.form.get("zona_sismica", "").strip()
        notas = request.form.get("notas", "").strip()

        # Zona sísmica: input directo tiene prioridad
        nueva_zona = None
        if zona_raw:
            try:
                nueva_zona = int(zona_raw)
            except ValueError:
                nueva_zona = proyecto.get("zona_sismica")
        else:
            nueva_zona = proyecto.get("zona_sismica")

        zona_anterior = proyecto.get("zona_sismica")

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

        # Agregar nuevos elementos si vienen en el form
        nuevos_elementos = request.form.get("nuevos_elementos", "").strip()
        if nuevos_elementos:
            for item in nuevos_elementos.split(","):
                item = item.strip()
                if ":" in item:
                    partes = item.split(":")
                    nombre_elem = partes[0].strip()
                    codigo_elem = partes[1].strip().upper()
                    familia_elem = partes[2].strip().upper() if len(partes) > 2 else "OBR"
                    if nombre_elem and codigo_elem:
                        # Verificar que no exista ya
                        existe = db.execute(
                            "SELECT id FROM elementos_proyecto WHERE proyecto_id = ? AND codigo = ?",
                            (proyecto_id, codigo_elem)
                        ).fetchone()
                        if not existe:
                            db.execute(
                                "INSERT INTO elementos_proyecto (proyecto_id, codigo, nombre, familia, orden) VALUES (?,?,?,?,?)",
                                (proyecto_id, codigo_elem, nombre_elem, familia_elem, 100)
                            )
                            cambios.append(f"elemento agregado: {codigo_elem} ({nombre_elem})")

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
    return render_template("editar_proyecto.html", proyecto=proyecto, comunas=COMUNAS, elementos=elementos)


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

    documentos = db.execute(
        """SELECT d.*, e.codigo as elem_codigo, e.nombre as elem_nombre 
           FROM documentos d 
           LEFT JOIN elementos_proyecto e ON d.elemento_id = e.id 
           WHERE d.proyecto_id = ? AND d.activo = 1 
           ORDER BY d.codigo_completo""",
        (proyecto_id,)
    ).fetchall()

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

    return render_template("proyecto.html", proyecto=proyecto, documentos=documentos,
                           solicitudes=solicitudes, resumen=resumen,
                           config_modulos=config_modulos, config_tipos=config_tipos,
                           elementos=elementos, actas=actas,
                           num_tipologias=len([e for e in elementos if e["familia"] == "VIV"]))

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
    return render_template("config.html", modulos=modulos, tipos=tipos)

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

# ──────────────────────────────────────────────────────────────
# CEMENTERIO
# ──────────────────────────────────────────────────────────────
@app.route("/cementerio")
def cementerio():
    db = get_db()
    eliminados = db.execute(
        """SELECT de.*, p.acronimo, p.nombre
        FROM documentos_eliminados de
        JOIN proyectos p ON de.proyecto_id = p.id
        ORDER BY de.fecha_eliminacion DESC"""
    ).fetchall()
    return render_template("cementerio.html", eliminados=eliminados)

# ──────────────────────────────────────────────────────────────
# HISTORIAL
# ──────────────────────────────────────────────────────────────
@app.route("/historial/<int:proyecto_id>")
def ver_historial(proyecto_id):
    db = get_db()
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
    historial = db.execute("""
        SELECT h.*, d.codigo_completo as doc_codigo
        FROM historial h
        LEFT JOIN documentos d ON h.documento_id = d.id
        WHERE h.proyecto_id = ?
        ORDER BY h.fecha DESC
    """, (proyecto_id,)).fetchall()
    return render_template("historial.html", proyecto=proyecto, historial=historial)

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
if __name__ == "__main__":
    if not DATABASE.exists():
        init_db()
    else:
        migrate_db()
    app.run(debug=False, host="0.0.0.0", port=5000)
