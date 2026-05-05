-- Migracion: poblar tabla acta_items con items de los formatos OFICIALES
-- Fuente de verdad: capturas de pantalla del acta de Estructuras del usuario
-- Ejecutar una sola vez despues de crear la tabla acta_items

-- ============================================
-- EST (Estructuras) — Secciones A-J: PLANOS
-- Tipo de documento: PLN
-- ============================================
INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'A. Comparativa con Arquitectura', 'A.1', 'Planos deben estar en ejes y modulos acorde a los planos arquitectonicos.', 'PLN', 1),
('EST', 'A. Comparativa con Arquitectura', 'A.2', 'Verificacion en terreno de ubicacion de estructura en relacion a limites de terreno, linderos y vias de acceso.', 'PLN', 2),
('EST', 'A. Comparativa con Arquitectura', 'A.3', 'Trazo y ubicacion en terreno en relacion con planos aprobados por el Servicio de Vivienda y Urbanizacion (Se deja constancia de que el trazado se realizo aprobado por el SERVIU).', 'PLN', 3),
('EST', 'A. Comparativa con Arquitectura', 'A.4', 'Tabiqueria y distanciamiento de tabiques, division de ambientes en planta y en elevaciones.', 'PLN', 4),
('EST', 'A. Comparativa con Arquitectura', 'A.5', 'Ventilaciones.', 'PLN', 5);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'B. Planta de fundaciones y detalles', 'B.1', 'Cotas y dimensiones de fundaciones y/o elementos constructivos.', 'PLN', 6),
('EST', 'B. Planta de fundaciones y detalles', 'B.2', 'Union de fundaciones y/o elementos constructivos entre si.', 'PLN', 7),
('EST', 'B. Planta de fundaciones y detalles', 'B.3', 'Secciones, detalles y dimensiones de fundaciones y/o elementos constructivos.', 'PLN', 8);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'C. Secciones', 'C.1', 'Espesor, armaduras, distanciamiento de armadura, dobleces y enfierraduras en elementos de estructura, segun normativa vigente.', 'PLN', 9);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'D. Planta de Estructuras', 'D.1', 'Ejes, armaduras, identificacion de espesores de elementos, enfierraduras y tabiqueria en elementos estructurales, segun normativa vigente.', 'PLN', 10);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'E. Planta de losas', 'E.1', 'Armaduras de refuerzo, dobleces, identificacion y ubicacion de losas segun normativa vigente.', 'PLN', 11);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'F. Planta de techumbre y detalles', 'F.1', 'Cerchas, perfiles estructurales, elementos y tipo de conexiones en elementos de techumbre.', 'PLN', 12),
('EST', 'F. Planta de techumbre y detalles', 'F.2', 'Elevaciones de ejes de techumbre y elementos.', 'PLN', 13),
('EST', 'F. Planta de techumbre y detalles', 'F.3', 'Detalles constructivos y enfierraduras de techumbre.', 'PLN', 14);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'G. Elevaciones de ejes estructurales', 'G.1', 'Muros, armadura, enfierraduras y dimensiones, segun normativa vigente.', 'PLN', 15);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'H. Planos de escalera y detalles', 'H.1', 'Materialidad, dimensiones, elementos y tipo de uniones de escalera, segun normativa vigente.', 'PLN', 16);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'I. Detalles constructivos', 'I.1', 'Amarras en elementos de hormigon.', 'PLN', 17),
('EST', 'I. Detalles constructivos', 'I.2', 'Estribos.', 'PLN', 18),
('EST', 'I. Detalles constructivos', 'I.3', 'Juntas en elementos de estructura y de construccion.', 'PLN', 19),
('EST', 'I. Detalles constructivos', 'I.4', 'Enfierraduras y uniones.', 'PLN', 20),
('EST', 'I. Detalles constructivos', 'I.5', 'Alfeizares.', 'PLN', 21);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'J. Especificaciones tecnicas de planos', 'J.1', 'Materialidad de elementos de estructura, emplazamiento, zona sismica, suelo, acero, pernos, barras, tipos de fundaciones, resistencia caracteristica de hormigon y cerchas.', 'PLN', 23);

-- ============================================
-- EST (Estructuras) — Secciones K-Q: MEMORIAS
-- Tipo de documento: MEM
-- ============================================
INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'K. Descripcion del proyecto', 'K.1', 'Descripcion general del proyecto, materialidad y emplazamiento.', 'MEM', 24);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'L. Normativa vigente', 'L.1', 'Incluye y cita normativa vigente.', 'MEM', 25);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'M. Coherencia del proyecto', 'M.1', 'Coherente con otros documentos del proyecto.', 'MEM', 26);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'N. Cargas, sobrecargas y tensiones admisibles', 'N.1', 'Cargas de techumbre segun normativa vigente.', 'MEM', 27),
('EST', 'N. Cargas, sobrecargas y tensiones admisibles', 'N.2', 'Cargas de techumbre solar segun normativa vigente.', 'MEM', 28);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'O. Tabiques divisores', 'O.1', 'Consideracion de tabiques divisores en el analisis estructural.', 'MEM', 29);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'P. Entrepisos de madera o acero', 'P.1', 'Entrepisos de madera o acero.', 'MEM', 30);

INSERT INTO acta_items (modulo, seccion, codigo, descripcion, tipo_doc, orden) VALUES
('EST', 'Q. Calculo de elementos estructurales', 'Q.1', 'Madera.', 'MEM', 31),
('EST', 'Q. Calculo de elementos estructurales', 'Q.2', 'Acero.', 'MEM', 32),
('EST', 'Q. Calculo de elementos estructurales', 'Q.3', 'Hormigon.', 'MEM', 33),
('EST', 'Q. Calculo de elementos estructurales', 'Q.4', 'Albanileria.', 'MEM', 34),
('EST', 'Q. Calculo de elementos estructurales', 'Q.5', 'Fundacion.', 'MEM', 35);
lculo de elementos estructurales', 'Q.