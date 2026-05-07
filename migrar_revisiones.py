import sqlite3
from pathlib import Path

def migrar():
    db_path = Path(__file__).parent / "data" / "proyectos.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    print("🔄 Iniciando migración a módulo de revisiones técnicas + CHK...")

    # 1. Nuevas columnas en documentos
    columnas_nuevas = [
        ("elemento_id", "INTEGER"),
        ("familia", "TEXT DEFAULT ''"),
        ("elemento", "TEXT DEFAULT ''"),
        ("tipologia", "TEXT DEFAULT ''"),
        ("etapa", "TEXT DEFAULT 'CHK'"),
        ("estado_chk", "TEXT DEFAULT 'faltante'"),
        ("estado_tecnico", "TEXT"),
        ("ubicacion_fisica", "TEXT"),
        ("plantilla_tipo_id", "INTEGER"),
        ("revision_actual_id", "INTEGER"),
        ("revision_count", "INTEGER DEFAULT 0"),
    ]

    cursor = conn.execute("PRAGMA table_info(documentos)")
    cols_existentes = {row["name"] for row in cursor.fetchall()}

    for nombre, definicion in columnas_nuevas:
        if nombre not in cols_existentes:
            conn.execute(f"ALTER TABLE documentos ADD COLUMN {nombre} {definicion}")
            print(f"   ✅ Columna '{nombre}' agregada a documentos")
        else:
            print(f"   ℹ️  Columna '{nombre}' ya existe")

    # 2. Tablas nuevas
    tablas = [
        ("plantillas_tipo", """
            CREATE TABLE IF NOT EXISTS plantillas_tipo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT UNIQUE NOT NULL,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                disciplina TEXT NOT NULL,
                orden_flujo INTEGER,
                anticipar_para TEXT DEFAULT 'todos',
                activo INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("secciones_plantilla", """
            CREATE TABLE IF NOT EXISTS secciones_plantilla (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plantilla_id INTEGER NOT NULL REFERENCES plantillas_tipo(id) ON DELETE CASCADE,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                orden INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("items_plantilla", """
            CREATE TABLE IF NOT EXISTS items_plantilla (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seccion_id INTEGER NOT NULL REFERENCES secciones_plantilla(id) ON DELETE CASCADE,
                texto TEXT NOT NULL,
                ayuda TEXT,
                orden INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("revisiones", """
            CREATE TABLE IF NOT EXISTS revisiones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
                proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
                tipo TEXT NOT NULL DEFAULT 'tecnica',
                etapa TEXT,
                estado TEXT NOT NULL DEFAULT 'pendiente',
                iniciada_at TIMESTAMP,
                finalizada_at TIMESTAMP,
                notas_generales TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("checklist_revision", """
            CREATE TABLE IF NOT EXISTS checklist_revision (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                revision_id INTEGER NOT NULL REFERENCES revisiones(id) ON DELETE CASCADE,
                item_id INTEGER NOT NULL REFERENCES items_plantilla(id) ON DELETE CASCADE,
                estado TEXT,
                observacion_id INTEGER REFERENCES observaciones(id) ON DELETE SET NULL,
                marcado_at TIMESTAMP,
                comentario_item TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("observaciones", """
            CREATE TABLE IF NOT EXISTS observaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'tecnica',
                revision_id INTEGER REFERENCES revisiones(id) ON DELETE SET NULL,
                documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
                proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
                seccion_nombre TEXT,
                item_texto TEXT,
                estado TEXT NOT NULL DEFAULT 'no_conforme',
                severidad TEXT,
                descripcion TEXT NOT NULL,
                fundamento_normativo TEXT,
                accion_correctiva TEXT,
                resuelta INTEGER NOT NULL DEFAULT 0,
                resuelta_at TIMESTAMP,
                resuelta_comentario TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("obs_refs", """
            CREATE TABLE IF NOT EXISTS obs_refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observacion_id INTEGER NOT NULL REFERENCES observaciones(id) ON DELETE CASCADE,
                documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
                ubicacion_exacta TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("cruces_pendientes", """
            CREATE TABLE IF NOT EXISTS cruces_pendientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
                origen_disciplina TEXT NOT NULL,
                destino_disciplina TEXT NOT NULL,
                descripcion TEXT NOT NULL,
                documento_origen_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
                documento_destino_id INTEGER REFERENCES documentos(id) ON DELETE SET NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente',
                observacion_generada_id INTEGER REFERENCES observaciones(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verificado_at TIMESTAMP
            )
        """),
    ]

    for nombre, sql in tablas:
        conn.execute(sql)
        print(f"   ✅ Tabla '{nombre}' creada o ya existe")

    # 3. Índices
    indices = [
        "CREATE INDEX IF NOT EXISTS idx_doc_proyecto_estado ON documentos(proyecto_id, estado_chk)",
        "CREATE INDEX IF NOT EXISTS idx_doc_etapa ON documentos(proyecto_id, etapa)",
        "CREATE INDEX IF NOT EXISTS idx_revisiones_documento ON revisiones(documento_id)",
        "CREATE INDEX IF NOT EXISTS idx_revisiones_tipo ON revisiones(documento_id, tipo)",
        "CREATE INDEX IF NOT EXISTS idx_checklist_revision ON checklist_revision(revision_id)",
        "CREATE INDEX IF NOT EXISTS idx_observaciones_proyecto ON observaciones(proyecto_id)",
        "CREATE INDEX IF NOT EXISTS idx_observaciones_tipo ON observaciones(proyecto_id, tipo)",
        "CREATE INDEX IF NOT EXISTS idx_observaciones_documento ON observaciones(documento_id)",
        "CREATE INDEX IF NOT EXISTS idx_cruces_proyecto ON cruces_pendientes(proyecto_id, estado)",
    ]

    for sql in indices:
        conn.execute(sql)
        print(f"   ✅ Índice creado")

    # 4. Seed data: plantillas_tipo
    plantillas = [
        ('INF_MDS', 'Informe Mecánica de Suelos', 'Informe geotécnico del proyecto', 'MDS', 1, 'glb'),
        ('MEM_HAB', 'Memoria de Habilitación', 'Memoria descriptiva de habilitación urbana', 'HAB', 2, 'glb'),
        ('PLAN_HAB', 'Planos de Habilitación', 'Planos de habilitación y urbanización', 'HAB', 2, 'glb'),
        ('MEM_EST', 'Memoria de Cálculo Estructural', 'Memoria de cálculo de elementos estructurales', 'EST', 3, 'tipologias'),
        ('PLAN_EST', 'Planos Estructurales', 'Planos de estructuras y detalles constructivos', 'EST', 3, 'tipologias'),
        ('LAB', 'Ensayos de Laboratorio', 'Ensayos geotécnicos de laboratorio', 'LAB', 1, 'glb'),
    ]

    for codigo, nombre, desc, disc, orden, anticipar in plantillas:
        conn.execute("""
            INSERT OR IGNORE INTO plantillas_tipo (codigo, nombre, descripcion, disciplina, orden_flujo, anticipar_para)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (codigo, nombre, desc, disc, orden, anticipar))
    print(f"   ✅ {len(plantillas)} tipos de documento inicializados")

    # 5. Migrar documentos existentes: asignar valores por defecto
    conn.execute("UPDATE documentos SET etapa = 'CHK' WHERE etapa IS NULL")
    conn.execute("UPDATE documentos SET version = 1 WHERE version IS NULL OR version = 0")
    conn.execute("UPDATE documentos SET estado_chk = 'sin_observacion' WHERE estado_chk IS NULL")
    conn.execute("UPDATE documentos SET revision_count = 0 WHERE revision_count IS NULL")
    print(f"   ✅ Documentos existentes migrados")

    conn.commit()
    print("\n🎉 Migración completada exitosamente.")
    conn.close()

if __name__ == "__main__":
    migrar()
