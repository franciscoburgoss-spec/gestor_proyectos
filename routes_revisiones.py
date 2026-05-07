# -*- coding: utf-8 -*-
"""
Módulo de Revisiones Técnicas + CHK Recepción
Blueprint para Flask — registra en app.py como revisiones_bp
"""
import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
from datetime import datetime
from database import get_db

revisiones_bp = Blueprint("revisiones", __name__, url_prefix="/revisiones")


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

def _get_db():
    """Obtiene conexión a la base de datos desde el contexto de Flask."""
    if "db" not in g:
        from pathlib import Path
        db_path = Path(__file__).parent / "data" / "proyectos.db"
        g.db = sqlite3.connect(str(db_path))
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

def _generar_codigo_obs(proyecto_id, db):
    """Genera siguiente código OBS para un proyecto."""
    count = db.execute(
        "SELECT COUNT(*) as n FROM observaciones WHERE proyecto_id = ?",
        (proyecto_id,)
    ).fetchone()["n"]
    return f"OBS-{count + 1:03d}"

def _estadisticas_chk(proyecto_id, db):
    """Retorna contadores del CHK para un proyecto."""
    stats = db.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN estado_chk = 'sin_observacion' THEN 1 ELSE 0 END) as ok,
            SUM(CASE WHEN estado_chk = 'con_observacion' THEN 1 ELSE 0 END) as obs,
            SUM(CASE WHEN estado_chk = 'faltante' THEN 1 ELSE 0 END) as falt
        FROM documentos
        WHERE proyecto_id = ? AND etapa = 'CHK' AND activo = 1
    """, (proyecto_id,)).fetchone()
    return {
        "total": stats["total"] or 0,
        "ok": stats["ok"] or 0,
        "obs": stats["obs"] or 0,
        "falt": stats["falt"] or 0,
        "completo": (stats["ok"] or 0) == (stats["total"] or 0) and (stats["total"] or 0) > 0
    }


# ──────────────────────────────────────────────────────────────
# 1. CONFIGURACIÓN DE PLANTILLAS
# ──────────────────────────────────────────────────────────────

@revisiones_bp.route("/config/plantillas")
def listar_plantillas():
    db = _get_db()
    plantillas = db.execute("SELECT * FROM plantillas_tipo ORDER BY orden_flujo, nombre").fetchall()
    return render_template("revisiones/plantillas_lista.html", plantillas=plantillas)


@revisiones_bp.route("/config/plantillas/nuevo", methods=["GET", "POST"])
def nueva_plantilla():
    db = _get_db()
    if request.method == "POST":
        codigo = request.form["codigo"].strip().upper()
        nombre = request.form["nombre"].strip()
        disciplina = request.form["disciplina"].upper()
        orden = int(request.form.get("orden_flujo", 0))
        anticipar = request.form.get("anticipar_para", "todos")
        
        try:
            db.execute("""
                INSERT INTO plantillas_tipo (codigo, nombre, disciplina, orden_flujo, anticipar_para)
                VALUES (?, ?, ?, ?, ?)
            """, (codigo, nombre, disciplina, orden, anticipar))
            db.commit()
            
            # Crear 5 secciones por defecto
            plantilla_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            secciones = [
                "Estructura del documento",
                "Contexto y ubicación",
                "Coherencia tipológica",
                "Consistencia interna y cruzada",
                "Detalle técnico"
            ]
            for i, nombre_sec in enumerate(secciones, 1):
                db.execute("""
                    INSERT INTO secciones_plantilla (plantilla_id, nombre, orden)
                    VALUES (?, ?, ?)
                """, (plantilla_id, nombre_sec, i))
            db.commit()
            flash(f"Plantilla '{nombre}' creada con 5 secciones por defecto.", "ok")
        except sqlite3.IntegrityError:
            flash(f"El código '{codigo}' ya existe.", "err")
        return redirect(url_for("revisiones.listar_plantillas"))
    
    return render_template("revisiones/plantilla_nueva.html")


@revisiones_bp.route("/config/plantillas/<int:id>")
def ver_plantilla(id):
    db = _get_db()
    plantilla = db.execute("SELECT * FROM plantillas_tipo WHERE id = ?", (id,)).fetchone()
    if not plantilla:
        flash("Plantilla no encontrada.", "err")
        return redirect(url_for("revisiones.listar_plantillas"))
    
    secciones = db.execute("""
        SELECT s.*, COUNT(i.id) as num_items
        FROM secciones_plantilla s
        LEFT JOIN items_plantilla i ON i.seccion_id = s.id
        WHERE s.plantilla_id = ?
        GROUP BY s.id
        ORDER BY s.orden
    """, (id,)).fetchall()
    
    return render_template("revisiones/plantilla_ver.html", plantilla=plantilla, secciones=secciones)


@revisiones_bp.route("/config/plantillas/<int:id>/editar", methods=["POST"])
def editar_plantilla(id):
    db = _get_db()
    nombre = request.form["nombre"].strip()
    disciplina = request.form["disciplina"].upper()
    orden = int(request.form.get("orden_flujo", 0))
    anticipar = request.form.get("anticipar_para", "todos")
    
    db.execute("""
        UPDATE plantillas_tipo SET nombre=?, disciplina=?, orden_flujo=?, anticipar_para=?
        WHERE id=?
    """, (nombre, disciplina, orden, anticipar, id))
    db.commit()
    flash("Plantilla actualizada.", "ok")
    return redirect(url_for("revisiones.ver_plantilla", id=id))


@revisiones_bp.route("/config/secciones/<int:plantilla_id>/nueva", methods=["POST"])
def nueva_seccion(plantilla_id):
    db = _get_db()
    nombre = request.form["nombre"].strip()
    orden = int(request.form.get("orden", 1))
    
    db.execute("""
        INSERT INTO secciones_plantilla (plantilla_id, nombre, orden)
        VALUES (?, ?, ?)
    """, (plantilla_id, nombre, orden))
    db.commit()
    flash("Sección agregada.", "ok")
    return redirect(url_for("revisiones.ver_plantilla", id=plantilla_id))


@revisiones_bp.route("/config/secciones/<int:id>/eliminar", methods=["POST"])
def eliminar_seccion(id):
    db = _get_db()
    plantilla_id = db.execute("SELECT plantilla_id FROM secciones_plantilla WHERE id=?", (id,)).fetchone()
    if plantilla_id:
        db.execute("DELETE FROM secciones_plantilla WHERE id=?", (id,))
        db.commit()
        flash("Sección eliminada.", "ok")
        return redirect(url_for("revisiones.ver_plantilla", id=plantilla_id["plantilla_id"]))
    flash("Sección no encontrada.", "err")
    return redirect(url_for("revisiones.listar_plantillas"))


@revisiones_bp.route("/config/items/<int:seccion_id>/nuevo", methods=["POST"])
def nuevo_item(seccion_id):
    db = _get_db()
    texto = request.form["texto"].strip()
    ayuda = request.form.get("ayuda", "").strip()
    orden = int(request.form.get("orden", 1))
    
    seccion = db.execute("SELECT plantilla_id FROM secciones_plantilla WHERE id=?", (seccion_id,)).fetchone()
    
    db.execute("""
        INSERT INTO items_plantilla (seccion_id, texto, ayuda, orden)
        VALUES (?, ?, ?, ?)
    """, (seccion_id, texto, ayuda, orden))
    db.commit()
    flash("Ítem agregado.", "ok")
    return redirect(url_for("revisiones.ver_plantilla", id=seccion["plantilla_id"]))


@revisiones_bp.route("/config/items/<int:id>/eliminar", methods=["POST"])
def eliminar_item(id):
    db = _get_db()
    row = db.execute("""
        SELECT i.id, s.plantilla_id 
        FROM items_plantilla i
        JOIN secciones_plantilla s ON s.id = i.seccion_id
        WHERE i.id = ?
    """, (id,)).fetchone()
    if row:
        db.execute("DELETE FROM items_plantilla WHERE id=?", (id,))
        db.commit()
        flash("Ítem eliminado.", "ok")
        return redirect(url_for("revisiones.ver_plantilla", id=row["plantilla_id"]))
    flash("Ítem no encontrado.", "err")
    return redirect(url_for("revisiones.listar_plantillas"))


# ──────────────────────────────────────────────────────────────
# 2. CHK — RECEPCIÓN DE DOCUMENTOS
# ──────────────────────────────────────────────────────────────

@revisiones_bp.route("/chk/<int:proyecto_id>")
def chk_dashboard(proyecto_id):
    db = _get_db()
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
    if not proyecto:
        flash("Proyecto no encontrado.", "err")
        return redirect(url_for("index"))
    
    documentos = db.execute("""
        SELECT d.*, e.nombre as elem_nombre, e.codigo as elem_codigo,
               pt.nombre as tipo_nombre, pt.disciplina
        FROM documentos d
        LEFT JOIN elementos_proyecto e ON e.id = d.elemento_id
        LEFT JOIN plantillas_tipo pt ON pt.id = d.plantilla_tipo_id
        WHERE d.proyecto_id = ? AND d.etapa = 'CHK' AND d.activo = 1
        ORDER BY pt.orden_flujo, e.orden, d.codigo_completo
    """, (proyecto_id,)).fetchall()
    
    stats = _estadisticas_chk(proyecto_id, db)
    
    # Observaciones de CHK (tipo='chk') que no están resueltas
    observaciones_chk = db.execute("""
        SELECT o.*, d.codigo_completo, d.titulo
        FROM observaciones o
        JOIN documentos d ON d.id = o.documento_id
        WHERE o.proyecto_id = ? AND o.tipo = 'chk' AND o.resuelta = 0
        ORDER BY o.created_at DESC
    """, (proyecto_id,)).fetchall()
    
    return render_template("revisiones/chk_dashboard.html",
                           proyecto=proyecto, documentos=documentos,
                           stats=stats, observaciones=observaciones_chk)


@revisiones_bp.route("/chk/<int:proyecto_id>/documento/<int:documento_id>/estado", methods=["POST"])
def chk_cambiar_estado(proyecto_id, documento_id):
    db = _get_db()
    nuevo_estado = request.form["estado"]  # sin_observacion | con_observacion | faltante
    ubicacion = request.form.get("ubicacion_fisica", "").strip()
    
    doc = db.execute("SELECT * FROM documentos WHERE id = ?", (documento_id,)).fetchone()
    if not doc:
        flash("Documento no encontrado.", "err")
        return redirect(url_for("revisiones.chk_dashboard", proyecto_id=proyecto_id))
    
    estado_anterior = doc["estado_chk"]
    
    db.execute("""
        UPDATE documentos SET estado_chk = ?, ubicacion_fisica = ?
        WHERE id = ?
    """, (nuevo_estado, ubicacion or doc["ubicacion_fisica"], documento_id))
    
    # Historial
    db.execute("""
        INSERT INTO historial (proyecto_id, documento_id, accion, valor_anterior, valor_nuevo, descripcion)
        VALUES (?, ?, 'chk_estado', ?, ?, 'Cambio estado CHK')
    """, (proyecto_id, documento_id, estado_anterior, nuevo_estado))
    
    db.commit()
    
    if nuevo_estado == "con_observacion":
        # Redirigir a form de observación CHK
        return redirect(url_for("revisiones.chk_observacion_nueva",
                                proyecto_id=proyecto_id, documento_id=documento_id))
    
    flash(f"Documento marcado como '{nuevo_estado}'.", "ok")
    return redirect(url_for("revisiones.chk_dashboard", proyecto_id=proyecto_id))


@revisiones_bp.route("/chk/<int:proyecto_id>/observacion/<int:documento_id>/nueva", methods=["GET", "POST"])
def chk_observacion_nueva(proyecto_id, documento_id):
    db = _get_db()
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
    documento = db.execute("SELECT * FROM documentos WHERE id = ?", (documento_id,)).fetchone()
    
    if not proyecto or not documento:
        flash("Proyecto o documento no encontrado.", "err")
        return redirect(url_for("revisiones.chk_dashboard", proyecto_id=proyecto_id))
    
    if request.method == "POST":
        descripcion = request.form["descripcion"].strip()
        accion_correctiva = request.form.get("accion_correctiva", "").strip()
        
        codigo = _generar_codigo_obs(proyecto_id, db)
        
        db.execute("""
            INSERT INTO observaciones (codigo, tipo, documento_id, proyecto_id,
                                       descripcion, accion_correctiva, estado)
            VALUES (?, 'chk', ?, ?, ?, ?, 'no_conforme')
        """, (codigo, documento_id, proyecto_id, descripcion, accion_correctiva))
        
        # Actualizar documento
        db.execute("UPDATE documentos SET estado_chk = 'con_observacion' WHERE id = ?", (documento_id,))
        
        db.commit()
        flash(f"Observación {codigo} registrada.", "ok")
        return redirect(url_for("revisiones.chk_dashboard", proyecto_id=proyecto_id))
    
    return render_template("revisiones/chk_observacion_nueva.html",
                         proyecto=proyecto, documento=documento)


@revisiones_bp.route("/chk/<int:proyecto_id>/observacion/<int:obs_id>/resolver", methods=["POST"])
def chk_resolver_observacion(proyecto_id, obs_id):
    db = _get_db()
    comentario = request.form.get("comentario", "").strip()
    
    obs = db.execute("SELECT * FROM observaciones WHERE id = ?", (obs_id,)).fetchone()
    if not obs:
        flash("Observación no encontrada.", "err")
        return redirect(url_for("revisiones.chk_dashboard", proyecto_id=proyecto_id))
    
    db.execute("""
        UPDATE observaciones
        SET resuelta = 1, resuelta_at = datetime('now'), resuelta_comentario = ?
        WHERE id = ?
    """, (comentario, obs_id))
    
    # Actualizar documento a sin_observacion si es la única obs pendiente
    doc_id = obs["documento_id"]
    pendientes = db.execute("""
        SELECT COUNT(*) as n FROM observaciones
        WHERE documento_id = ? AND tipo = 'chk' AND resuelta = 0
    """, (doc_id,)).fetchone()["n"]
    
    if pendientes == 0:
        db.execute("UPDATE documentos SET estado_chk = 'sin_observacion' WHERE id = ?", (doc_id,))
    
    db.commit()
    flash("Observación resuelta.", "ok")
    return redirect(url_for("revisiones.chk_dashboard", proyecto_id=proyecto_id))


@revisiones_bp.route("/chk/<int:proyecto_id>/email")
def chk_generar_email(proyecto_id):
    db = _get_db()
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
    
    # Documentos con observación
    con_obs = db.execute("""
        SELECT d.codigo_completo, d.titulo, o.descripcion, o.accion_correctiva
        FROM observaciones o
        JOIN documentos d ON d.id = o.documento_id
        WHERE o.proyecto_id = ? AND o.tipo = 'chk' AND o.resuelta = 0
        ORDER BY d.codigo_completo
    """, (proyecto_id,)).fetchall()
    
    # Documentos faltantes
    faltantes = db.execute("""
        SELECT codigo_completo, titulo
        FROM documentos
        WHERE proyecto_id = ? AND etapa = 'CHK' AND estado_chk = 'faltante' AND activo = 1
        ORDER BY codigo_completo
    """, (proyecto_id,)).fetchall()
    
    lines = ["Estimado Coordinador,", ""]
    lines.append(f"Adjunto resultado del Checklist de ingreso para {proyecto['acronimo']}:")
    lines.append("")
    
    if con_obs:
        lines.append(f"DOCUMENTOS CON OBSERVACIÓN ({len(con_obs)}):")
        for d in con_obs:
            lines.append(f"• {d['codigo_completo']} — {d['descripcion']}")
            if d['accion_correctiva']:
                lines.append(f"  → Se solicita: {d['accion_correctiva']}")
        lines.append("")
    
    if faltantes:
        lines.append(f"DOCUMENTOS FALTANTES ({len(faltantes)}):")
        for d in faltantes:
            lines.append(f"• {d['codigo_completo']} — {d['titulo']}")
        lines.append("")
    
    if not con_obs and not faltantes:
        lines.append("✅ Todos los documentos recibidos sin observaciones.")
        lines.append("")
    
    lines.append("Quedo atento a las correcciones para continuar con el proceso.")
    lines.append("")
    lines.append("Saludos,")
    
    contenido = "\n".join(lines)
    
    from flask import send_file
    import io
    buffer = io.BytesIO(contenido.encode("utf-8"))
    buffer.seek(0)
    
    return send_file(
        buffer,
        mimetype="text/plain",
        as_attachment=True,
        download_name=f"chk_{proyecto['acronimo']}_{datetime.now().strftime('%Y%m%d')}.txt"
    )


@revisiones_bp.route("/chk/<int:proyecto_id>/completar", methods=["POST"])
def chk_completar(proyecto_id):
    db = _get_db()
    stats = _estadisticas_chk(proyecto_id, db)
    
    if not stats["completo"]:
        flash("No se puede completar CHK: hay documentos con observación o faltantes.", "err")
        return redirect(url_for("revisiones.chk_dashboard", proyecto_id=proyecto_id))
    
    # Marcar todos los documentos CHK como listos para transición
    db.execute("""
        UPDATE documentos SET estado = 'chk_completo'
        WHERE proyecto_id = ? AND etapa = 'CHK' AND activo = 1
    """, (proyecto_id,))
    
    # Historial
    db.execute("""
        INSERT INTO historial (proyecto_id, accion, descripcion)
        VALUES (?, 'chk_completado', 'CHK completado. Todos los documentos sin observación.')
    """, (proyecto_id,))
    
    db.commit()
    flash("CHK completado. Ahora puedes copiar documentos a /R01/ y crear la solicitud R01.", "ok")
    return redirect(url_for("ver_proyecto", proyecto_id=proyecto_id))


# ──────────────────────────────────────────────────────────────
# 3. REVISIONES TÉCNICAS (R01, R02)
# ──────────────────────────────────────────────────────────────

@revisiones_bp.route("/revisar/<int:documento_id>")
def revisar_documento(documento_id):
    db = _get_db()
    documento = db.execute("""
        SELECT d.*, p.acronimo, p.nombre as proyecto_nombre, p.id as proyecto_id,
               pt.nombre as tipo_nombre, pt.disciplina
        FROM documentos d
        JOIN proyectos p ON p.id = d.proyecto_id
        LEFT JOIN plantillas_tipo pt ON pt.id = d.plantilla_tipo_id
        WHERE d.id = ?
    """, (documento_id,)).fetchone()
    
    if not documento:
        flash("Documento no encontrado.", "err")
        return redirect(url_for("index"))
    
    # Buscar revisión en progreso
    revision = db.execute("""
        SELECT * FROM revisiones
        WHERE documento_id = ? AND estado = 'en_progreso'
        ORDER BY id DESC LIMIT 1
    """, (documento_id,)).fetchone()
    
    if not revision:
        # Crear nueva revisión
        etapa = documento["etapa"] or "R01"
        db.execute("""
            INSERT INTO revisiones (documento_id, proyecto_id, tipo, etapa, estado, iniciada_at)
            VALUES (?, ?, 'tecnica', ?, 'en_progreso', datetime('now'))
        """, (documento_id, documento["proyecto_id"], etapa))
        db.commit()
        revision_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        
        # Generar checklist desde plantilla
        if documento["plantilla_tipo_id"]:
            items = db.execute("""
                SELECT i.*, s.nombre as seccion_nombre, s.orden as seccion_orden
                FROM items_plantilla i
                JOIN secciones_plantilla s ON s.id = i.seccion_id
                WHERE s.plantilla_id = ?
                ORDER BY s.orden, i.orden
            """, (documento["plantilla_tipo_id"],)).fetchall()
            
            for item in items:
                db.execute("""
                    INSERT INTO checklist_revision (revision_id, item_id)
                    VALUES (?, ?)
                """, (revision_id, item["id"]))
            db.commit()
    else:
        revision_id = revision["id"]
    
    # Cargar checklist con secciones agrupadas
    checklist = db.execute("""
        SELECT cr.*, i.texto, i.ayuda, s.nombre as seccion, s.orden as sec_orden, i.orden as item_orden
        FROM checklist_revision cr
        JOIN items_plantilla i ON i.id = cr.item_id
        JOIN secciones_plantilla s ON s.id = i.seccion_id
        WHERE cr.revision_id = ?
        ORDER BY s.orden, i.orden
    """, (revision_id,)).fetchall()
    
    # Observaciones previas del documento (para contexto)
    obs_previas = db.execute("""
        SELECT o.*, d.codigo_completo
        FROM observaciones o
        JOIN documentos d ON d.id = o.documento_id
        WHERE o.documento_id = ? AND o.tipo = 'tecnica' AND o.resuelta = 0
        ORDER BY o.created_at DESC
    """, (documento_id,)).fetchall()
    
    return render_template("revisiones/revisar_documento.html",
                           documento=documento, checklist=checklist,
                           revision_id=revision_id, observaciones=obs_previas)


@revisiones_bp.route("/revisar/checklist/<int:check_id>/marcar", methods=["POST"])
def marcar_item_checklist(check_id):
    db = _get_db()
    estado = request.form["estado"]  # conforme | no_conforme | no_aplica
    comentario = request.form.get("comentario", "").strip()
    
    check = db.execute("""
        SELECT cr.*, r.documento_id, r.proyecto_id
        FROM checklist_revision cr
        JOIN revisiones r ON r.id = cr.revision_id
        WHERE cr.id = ?
    """, (check_id,)).fetchone()
    
    if not check:
        return jsonify({"error": "Ítem no encontrado"}), 404
    
    observacion_id = check["observacion_id"]
    
    if estado == "no_conforme":
        # Crear observación técnica
        item = db.execute("SELECT * FROM items_plantilla WHERE id = ?", (check["item_id"],)).fetchone()
        seccion = db.execute("SELECT * FROM secciones_plantilla WHERE id = ?", (item["seccion_id"],)).fetchone()
        
        codigo = _generar_codigo_obs(check["proyecto_id"], db)
        db.execute("""
            INSERT INTO observaciones (codigo, tipo, revision_id, documento_id, proyecto_id,
                                       seccion_nombre, item_texto, estado, descripcion)
            VALUES (?, 'tecnica', ?, ?, ?, ?, ?, 'no_conforme', ?)
        """, (codigo, check["revision_id"], check["documento_id"], check["proyecto_id"],
               seccion["nombre"], item["texto"], comentario or "Observación desde checklist"))
        observacion_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    elif estado in ("conforme", "no_aplica") and observacion_id:
        # Si cambia a conforme/no_aplica, desvincular observación
        observacion_id = None
    
    db.execute("""
        UPDATE checklist_revision
        SET estado = ?, comentario_item = ?, observacion_id = ?, marcado_at = datetime('now')
        WHERE id = ?
    """, (estado, comentario, observacion_id, check_id))
    db.commit()
    
    return jsonify({"ok": True, "estado": estado, "observacion_id": observacion_id})


@revisiones_bp.route("/revisar/<int:revision_id>/finalizar", methods=["POST"])
def finalizar_revision(revision_id):
    db = _get_db()
    notas = request.form.get("notas_generales", "").strip()
    
    revision = db.execute("SELECT * FROM revisiones WHERE id = ?", (revision_id,)).fetchone()
    if not revision:
        flash("Revisión no encontrada.", "err")
        return redirect(url_for("index"))
    
    doc_id = revision["documento_id"]
    proyecto_id = revision["proyecto_id"]
    
    # Contar resultados
    stats = db.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN estado = 'conforme' THEN 1 ELSE 0 END) as conforme,
            SUM(CASE WHEN estado = 'no_conforme' THEN 1 ELSE 0 END) as no_conforme,
            SUM(CASE WHEN estado = 'no_aplica' THEN 1 ELSE 0 END) as no_aplica
        FROM checklist_revision
        WHERE revision_id = ?
    """, (revision_id,)).fetchone()
    
    # Determinar estado del documento
    if stats["no_conforme"] > 0:
        estado_doc = "observado"
    else:
        estado_doc = "aprobado"
    
    db.execute("""
        UPDATE revisiones
        SET estado = 'completada', finalizada_at = datetime('now'), notas_generales = ?
        WHERE id = ?
    """, (notas, revision_id))
    
    db.execute("""
        UPDATE documentos
        SET estado_tecnico = ?, revision_count = revision_count + 1, revision_actual_id = NULL
        WHERE id = ?
    """, (estado_doc, doc_id))
    
    # Generar cruces pendientes si aplica
    if estado_doc == "aprobado":
        _generar_cruces_pendientes(doc_id, proyecto_id, db)
    
    db.commit()
    flash(f"Revisión finalizada. Documento {estado_doc}.", "ok")
    return redirect(url_for("ver_proyecto", proyecto_id=proyecto_id))


def _generar_cruces_pendientes(doc_id, proyecto_id, db):
    """Genera cruces pendientes automáticos según disciplina del documento."""
    doc = db.execute("""
        SELECT d.*, pt.disciplina, pt.codigo
        FROM documentos d
        JOIN plantillas_tipo pt ON pt.id = d.plantilla_tipo_id
        WHERE d.id = ?
    """, (doc_id,)).fetchone()
    
    if not doc:
        return
    
    disciplina = doc["disciplina"]
    
    # Reglas de cruces según disciplina
    cruces_reglas = {
        "MDS": [("EST", "Verificar parámetros de fundación en memoria de cálculo estructural")],
        "HAB": [("EST", "Confirmar que evacuación pluvial fue considerada en estructuras")],
        "EST": [
            ("MDS", "Verificar que cuantías respetan parámetros geotécnicos"),
            ("HAB", "Confirmar que estructura respeta límites de habilitación")
        ]
    }
    
    reglas = cruces_reglas.get(disciplina, [])
    for dest_disc, descripcion in reglas:
        # Buscar documento destino del mismo proyecto
        dest = db.execute("""
            SELECT d.id FROM documentos d
            JOIN plantillas_tipo pt ON pt.id = d.plantilla_tipo_id
            WHERE d.proyecto_id = ? AND pt.disciplina = ? AND d.etapa = ? AND d.activo = 1
            LIMIT 1
        """, (proyecto_id, dest_disc, doc["etapa"])).fetchone()
        
        if dest:
            db.execute("""
                INSERT INTO cruces_pendientes (proyecto_id, origen_disciplina, destino_disciplina,
                                               descripcion, documento_origen_id, documento_destino_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (proyecto_id, disciplina, dest_disc, descripcion, doc_id, dest["id"]))


# ──────────────────────────────────────────────────────────────
# 4. OBSERVACIONES
# ──────────────────────────────────────────────────────────────

@revisiones_bp.route("/observaciones/<int:proyecto_id>")
def listar_observaciones(proyecto_id):
    db = _get_db()
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
    
    tipo_filtro = request.args.get("tipo", "")
    estado_filtro = request.args.get("estado", "")
    
    sql = """
        SELECT o.*, d.codigo_completo, d.titulo
        FROM observaciones o
        JOIN documentos d ON d.id = o.documento_id
        WHERE o.proyecto_id = ?
    """
    params = [proyecto_id]
    
    if tipo_filtro:
        sql += " AND o.tipo = ?"
        params.append(tipo_filtro)
    if estado_filtro == "pendientes":
        sql += " AND o.resuelta = 0"
    elif estado_filtro == "resueltas":
        sql += " AND o.resuelta = 1"
    
    sql += " ORDER BY o.resuelta, o.created_at DESC"
    
    observaciones = db.execute(sql, params).fetchall()
    
    return render_template("revisiones/observaciones_lista.html",
                         proyecto=proyecto, observaciones=observaciones,
                         tipo_filtro=tipo_filtro, estado_filtro=estado_filtro)


@revisiones_bp.route("/observacion/<int:id>")
def ver_observacion(id):
    db = _get_db()
    obs = db.execute("""
        SELECT o.*, d.codigo_completo, d.titulo, p.acronimo
        FROM observaciones o
        JOIN documentos d ON d.id = o.documento_id
        JOIN proyectos p ON p.id = o.proyecto_id
        WHERE o.id = ?
    """, (id,)).fetchone()
    
    if not obs:
        flash("Observación no encontrada.", "err")
        return redirect(url_for("index"))
    
    refs = db.execute("""
        SELECT r.*, d.codigo_completo
        FROM obs_refs r
        JOIN documentos d ON d.id = r.documento_id
        WHERE r.observacion_id = ?
    """, (id,)).fetchall()
    
    return render_template("revisiones/observacion_ver.html", obs=obs, refs=refs)


@revisiones_bp.route("/observacion/<int:id>/editar", methods=["POST"])
def editar_observacion(id):
    db = _get_db()
    descripcion = request.form["descripcion"].strip()
    fundamento = request.form.get("fundamento_normativo", "").strip()
    accion = request.form.get("accion_correctiva", "").strip()
    severidad = request.form.get("severidad", "").strip()
    
    db.execute("""
        UPDATE observaciones
        SET descripcion = ?, fundamento_normativo = ?, accion_correctiva = ?, severidad = ?
        WHERE id = ?
    """, (descripcion, fundamento, accion, severidad, id))
    db.commit()
    flash("Observación actualizada.", "ok")
    return redirect(url_for("revisiones.ver_observacion", id=id))


@revisiones_bp.route("/observacion/<int:id>/resolver", methods=["POST"])
def resolver_observacion(id):
    db = _get_db()
    comentario = request.form.get("comentario", "").strip()
    
    db.execute("""
        UPDATE observaciones
        SET resuelta = 1, resuelta_at = datetime('now'), resuelta_comentario = ?
        WHERE id = ?
    """, (comentario, id))
    db.commit()
    flash("Observación marcada como resuelta.", "ok")
    return redirect(url_for("revisiones.ver_observacion", id=id))


@revisiones_bp.route("/observacion/<int:id>/ref", methods=["POST"])
def agregar_ref_observacion(id):
    db = _get_db()
    documento_id = request.form["documento_id"]
    ubicacion = request.form.get("ubicacion_exacta", "").strip()
    
    db.execute("""
        INSERT INTO obs_refs (observacion_id, documento_id, ubicacion_exacta)
        VALUES (?, ?, ?)
    """, (id, documento_id, ubicacion))
    db.commit()
    flash("Referencia cruzada agregada.", "ok")
    return redirect(url_for("revisiones.ver_observacion", id=id))


# ──────────────────────────────────────────────────────────────
# 5. CRUCES PENDIENTES
# ──────────────────────────────────────────────────────────────

@revisiones_bp.route("/cruces/<int:proyecto_id>")
def listar_cruces(proyecto_id):
    db = _get_db()
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
    
    cruces = db.execute("""
        SELECT c.*, 
               do.codigo_completo as doc_origen, dd.codigo_completo as doc_destino
        FROM cruces_pendientes c
        LEFT JOIN documentos do ON do.id = c.documento_origen_id
        LEFT JOIN documentos dd ON dd.id = c.documento_destino_id
        WHERE c.proyecto_id = ?
        ORDER BY c.estado, c.created_at DESC
    """, (proyecto_id,)).fetchall()
    
    return render_template("revisiones/cruces_lista.html", proyecto=proyecto, cruces=cruces)


@revisiones_bp.route("/cruces/<int:id>/verificar", methods=["POST"])
def verificar_cruce(id):
    db = _get_db()
    resultado = request.form["resultado"]  # verificado | no_aplica
    observacion_texto = request.form.get("observacion", "").strip()
    
    cruce = db.execute("SELECT * FROM cruces_pendientes WHERE id = ?", (id,)).fetchone()
    if not cruce:
        flash("Cruce no encontrado.", "err")
        return redirect(url_for("index"))
    
    obs_id = None
    if resultado == "no_aplica":
        pass  # Simplemente marca no_aplica
    elif observacion_texto:
        # Crear observación desde el cruce
        codigo = _generar_codigo_obs(cruce["proyecto_id"], db)
        db.execute("""
            INSERT INTO observaciones (codigo, tipo, proyecto_id, documento_id,
                                       descripcion, estado)
            VALUES (?, 'tecnica', ?, ?, ?, 'no_conforme')
        """, (codigo, cruce["proyecto_id"], cruce["documento_destino_id"], observacion_texto))
        obs_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    db.execute("""
        UPDATE cruces_pendientes
        SET estado = ?, observacion_generada_id = ?, verificado_at = datetime('now')
        WHERE id = ?
    """, (resultado, obs_id, id))
    db.commit()
    
    flash(f"Cruce marcado como {resultado}.", "ok")
    return redirect(url_for("revisiones.listar_cruces", proyecto_id=cruce["proyecto_id"]))


# ──────────────────────────────────────────────────────────────
# 6. UTILIDADES — Anticipar documentos
# ──────────────────────────────────────────────────────────────

def anticipar_documentos_proyecto(proyecto_id, db):
    """Genera documentos esperados para un proyecto según elementos + plantillas."""
    proyecto = db.execute("SELECT * FROM proyectos WHERE id = ?", (proyecto_id,)).fetchone()
    if not proyecto:
        return []
    
    elementos = db.execute("""
        SELECT * FROM elementos_proyecto
        WHERE proyecto_id = ? ORDER BY orden
    """, (proyecto_id,)).fetchall()
    
    plantillas = db.execute("SELECT * FROM plantillas_tipo WHERE activo = 1").fetchall()
    
    creados = []
    for elem in elementos:
        for pt in plantillas:
            # Verificar si aplica según anticipar_para
            if pt["anticipar_para"] == "glb" and elem["codigo"] != "GLB":
                continue
            if pt["anticipar_para"] == "tipologias" and not elem["codigo"].startswith("T"):
                continue
            
            # Generar código del documento
            codigo = f"{proyecto['acronimo']}-{pt['disciplina']}-{elem['codigo']}-{pt['codigo']}"
            
            # Verificar si ya existe
            existente = db.execute(
                "SELECT id FROM documentos WHERE codigo_completo = ?",
                (codigo,)
            ).fetchone()
            
            if existente:
                continue
            
            db.execute("""
                INSERT INTO documentos (proyecto_id, elemento_id, codigo_completo, acronimo,
                                       modulo, familia, elemento, tipo_documento, tipologia, revision, version,
                                       titulo, estado, etapa, estado_chk, plantilla_tipo_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '0', '1', ?, 'ingresado', 'CHK', 'faltante', ?)
            """, (proyecto_id, elem["id"], codigo, proyecto["acronimo"],
                  pt["disciplina"], elem["familia"], elem["codigo"], pt["codigo"], elem["codigo"],
                  f"{pt['nombre']} — {elem['nombre']}", pt["id"]))
            
            doc_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            
            # Crear revisión CHK
            db.execute("""
                INSERT INTO revisiones (documento_id, proyecto_id, tipo, estado)
                VALUES (?, ?, 'chk', 'pendiente')
            """, (doc_id, proyecto_id))
            
            creados.append(codigo)
    
    return creados
