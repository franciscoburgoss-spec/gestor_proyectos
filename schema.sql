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