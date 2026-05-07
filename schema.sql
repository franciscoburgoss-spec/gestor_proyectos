-- Esquema completo de base de datos
-- Plataforma de seguimiento de proyectos de ingeniería
-- Nomenclatura: PROY-MOD-FAM-ELEM-TIPO-REV-VER

PRAGMA foreign_keys = ON;

-- Tablas de configuración
CREATE TABLE IF NOT EXISTS config_modulos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    activo INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS config_tipos_documento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    activo INTEGER DEFAULT 1
);

-- Tabla de proyectos
CREATE TABLE IF NOT EXISTS proyectos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acronimo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    estado_global TEXT DEFAULT 'activo',
    estado_flujo TEXT DEFAULT 'sin_solicitud',
    carpeta_raiz TEXT NOT NULL,
    comuna TEXT,
    zona_sismica INTEGER,
    fecha_creacion TIMESTAMP DEFAULT (datetime('now','localtime')),
    fecha_cierre TIMESTAMP,
    motivo_cierre TEXT,
    notas TEXT
);

-- Tabla de elementos del proyecto
CREATE TABLE IF NOT EXISTS elementos_proyecto (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proyecto_id INTEGER NOT NULL,
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    familia TEXT NOT NULL DEFAULT 'OBR',
    orden INTEGER DEFAULT 0,
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id),
    CHECK (familia IN ('VIV', 'REC', 'TER', 'OBR', 'URB', 'GEN'))
);

-- Tabla de documentos
-- Nomenclatura: PROY-MOD-FAM-ELEM-TIPO-REV-VER
CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proyecto_id INTEGER NOT NULL,
    elemento_id INTEGER,
    codigo_completo TEXT NOT NULL UNIQUE,
    acronimo TEXT NOT NULL,
    modulo TEXT NOT NULL,
    familia TEXT NOT NULL,
    elemento TEXT NOT NULL,
    tipo_documento TEXT NOT NULL,
    revision TEXT NOT NULL,
    version TEXT NOT NULL,
    titulo TEXT NOT NULL,
    estado TEXT DEFAULT 'ingresado',
    ruta_fisica TEXT,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    activo INTEGER DEFAULT 1,
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id),
    FOREIGN KEY (elemento_id) REFERENCES elementos_proyecto(id) ON DELETE RESTRICT
);

-- Tabla de solicitudes (emails/entradas)
CREATE TABLE IF NOT EXISTS solicitudes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proyecto_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    numero_iteracion INTEGER DEFAULT 1,
    fecha_entrada TIMESTAMP NOT NULL,
    fecha_limite TIMESTAMP,
    notas TEXT,
    estado TEXT DEFAULT 'recibida',
    fecha_cierre TIMESTAMP,
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id)
);

-- Tabla de revisiones aplicadas
CREATE TABLE IF NOT EXISTS revisiones_aplicadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    solicitud_id INTEGER NOT NULL,
    documento_id INTEGER NOT NULL,
    resultado TEXT NOT NULL,
    comentarios TEXT,
    fecha_revision TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (solicitud_id) REFERENCES solicitudes(id),
    FOREIGN KEY (documento_id) REFERENCES documentos(id)
);

-- Tabla de actas
CREATE TABLE IF NOT EXISTS actas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proyecto_id INTEGER NOT NULL,
    solicitud_id INTEGER,
    tipo TEXT NOT NULL,
    ruta_archivo TEXT,
    fecha_generacion TIMESTAMP DEFAULT (datetime('now','localtime')),
    contenido_resumen TEXT,
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id),
    FOREIGN KEY (solicitud_id) REFERENCES solicitudes(id)
);

-- Tabla de historial (inmutable)
CREATE TABLE IF NOT EXISTS historial (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proyecto_id INTEGER NOT NULL,
    documento_id INTEGER,
    solicitud_id INTEGER,
    accion TEXT NOT NULL,
    valor_anterior TEXT,
    valor_nuevo TEXT,
    descripcion TEXT NOT NULL,
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla de documentos eliminados (cementerio)
CREATE TABLE IF NOT EXISTS documentos_eliminados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proyecto_id INTEGER NOT NULL,
    documento_id_original INTEGER NOT NULL,
    codigo_completo TEXT NOT NULL,
    titulo TEXT,
    ruta_fisica_original TEXT,
    razon_eliminacion TEXT NOT NULL,
    fecha_eliminacion TIMESTAMP DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id)
);

-- Tabla de tareas (independientes de proyectos)
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
);

-- Tabla de jornada laboral
CREATE TABLE IF NOT EXISTS jornada (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha DATE NOT NULL UNIQUE,
    entrada TIME,
    salida TIME,
    estado TEXT DEFAULT 'trabajado',
    notas TEXT,
    CHECK (estado IN ('trabajado', 'feriado', 'permiso'))
);

-- Tabla de ítems de acta por módulo
CREATE TABLE IF NOT EXISTS acta_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    modulo TEXT NOT NULL,
    seccion TEXT NOT NULL,
    codigo TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    tipo_doc TEXT,
    orden INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_acta_items_modulo ON acta_items(modulo);
CREATE INDEX IF NOT EXISTS idx_acta_items_tipo_doc ON acta_items(tipo_doc);

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_elem_proyecto ON elementos_proyecto(proyecto_id);
CREATE INDEX IF NOT EXISTS idx_doc_proyecto ON documentos(proyecto_id);
CREATE INDEX IF NOT EXISTS idx_doc_estado ON documentos(estado);
CREATE INDEX IF NOT EXISTS idx_sol_proyecto ON solicitudes(proyecto_id);
CREATE INDEX IF NOT EXISTS idx_hist_proyecto ON historial(proyecto_id);
CREATE INDEX IF NOT EXISTS idx_hist_documento ON historial(documento_id);
CREATE INDEX IF NOT EXISTS idx_tareas_estado ON tareas(estado);
CREATE INDEX IF NOT EXISTS idx_jornada_fecha ON jornada(fecha);

-- Datos iniciales de configuración
INSERT OR IGNORE INTO config_modulos (codigo, nombre) VALUES
('EST', 'Estructuras'),
('MDS', 'Mecánica de Suelos'),
('HAB', 'Habilitación'),
('URB', 'Urbanización'),
('ADM', 'Administrativo');

INSERT OR IGNORE INTO config_tipos_documento (codigo, nombre) VALUES
('MEM', 'Memoria de Cálculo'),
('PLN', 'Planimetría'),
('INF', 'Informes'),
('ENS', 'Ensayos de Laboratorio'),
('MHB', 'Memoria de Habilitación'),
('LEG', 'Documentación Legal');

-- ============================================================
-- MÓDULO DE REVISIONES TÉCNICAS + CHK RECEPCIÓN (v2)
-- ============================================================

-- Nuevas columnas en documentos (para documento único evolucionando)
ALTER TABLE documentos ADD COLUMN etapa TEXT DEFAULT 'CHK';
ALTER TABLE documentos ADD COLUMN version INTEGER DEFAULT 1;
ALTER TABLE documentos ADD COLUMN estado_chk TEXT DEFAULT 'faltante';
ALTER TABLE documentos ADD COLUMN estado_tecnico TEXT;
ALTER TABLE documentos ADD COLUMN ubicacion_fisica TEXT;
ALTER TABLE documentos ADD COLUMN plantilla_tipo_id INTEGER;
ALTER TABLE documentos ADD COLUMN revision_actual_id INTEGER;
ALTER TABLE documentos ADD COLUMN revision_count INTEGER DEFAULT 0;

-- Tablas de configuración (plantillas de revisión)
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
);

CREATE TABLE IF NOT EXISTS secciones_plantilla (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plantilla_id INTEGER NOT NULL REFERENCES plantillas_tipo(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    orden INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS items_plantilla (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seccion_id INTEGER NOT NULL REFERENCES secciones_plantilla(id) ON DELETE CASCADE,
    texto TEXT NOT NULL,
    ayuda TEXT,
    orden INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tablas core del módulo de revisiones
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
);

CREATE TABLE IF NOT EXISTS checklist_revision (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_id INTEGER NOT NULL REFERENCES revisiones(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items_plantilla(id) ON DELETE CASCADE,
    estado TEXT,
    observacion_id INTEGER REFERENCES observaciones(id) ON DELETE SET NULL,
    marcado_at TIMESTAMP,
    comentario_item TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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
);

CREATE TABLE IF NOT EXISTS obs_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observacion_id INTEGER NOT NULL REFERENCES observaciones(id) ON DELETE CASCADE,
    documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    ubicacion_exacta TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_doc_proyecto_estado ON documentos(proyecto_id, estado_chk);
CREATE INDEX IF NOT EXISTS idx_doc_etapa ON documentos(proyecto_id, etapa);
CREATE INDEX IF NOT EXISTS idx_revisiones_documento ON revisiones(documento_id);
CREATE INDEX IF NOT EXISTS idx_revisiones_tipo ON revisiones(documento_id, tipo);
CREATE INDEX IF NOT EXISTS idx_checklist_revision ON checklist_revision(revision_id);
CREATE INDEX IF NOT EXISTS idx_observaciones_proyecto ON observaciones(proyecto_id);
CREATE INDEX IF NOT EXISTS idx_observaciones_tipo ON observaciones(proyecto_id, tipo);
CREATE INDEX IF NOT EXISTS idx_observaciones_documento ON observaciones(documento_id);
CREATE INDEX IF NOT EXISTS idx_cruces_proyecto ON cruces_pendientes(proyecto_id, estado);

-- Seed data: tipos de documento para revisiones
INSERT OR IGNORE INTO plantillas_tipo (codigo, nombre, descripcion, disciplina, orden_flujo, anticipar_para) VALUES
('INF_MDS', 'Informe Mecánica de Suelos', 'Informe geotécnico del proyecto', 'MDS', 1, 'glb'),
('MEM_HAB', 'Memoria de Habilitación', 'Memoria descriptiva de habilitación urbana', 'HAB', 2, 'glb'),
('PLAN_HAB', 'Planos de Habilitación', 'Planos de habilitación y urbanización', 'HAB', 2, 'glb'),
('MEM_EST', 'Memoria de Cálculo Estructural', 'Memoria de cálculo de elementos estructurales', 'EST', 3, 'tipologias'),
('PLAN_EST', 'Planos Estructurales', 'Planos de estructuras y detalles constructivos', 'EST', 3, 'tipologias'),
('LAB', 'Ensayos de Laboratorio', 'Ensayos geotécnicos de laboratorio', 'LAB', 1, 'glb');