"""
Inicializa la base de datos y carga el plan de estudios oficial de las tres
carreras de Ingeniería de la Universidad Austral.

Uso: python init_db.py

Modelo:
  - Una materia (Subject) existe UNA sola vez aunque la compartan varias
    carreras (ver SHARED_NAMES).
  - El año y cuatrimestre de cada materia dependen de la carrera, por eso se
    guardan en la asociación CareerSubject.
  - Biomédica no usa cuatrimestres (cuatrimestre = None).
"""
import os
from dotenv import load_dotenv

load_dotenv()

from app import create_app, db
from app.models import User, Faculty, Career, Subject, CareerSubject, Category, CATEGORY_TREE
from app.utils import slugify


# ---------------------------------------------------------------------------
# Facultades: (nombre, slug, orden)
# ---------------------------------------------------------------------------
FACULTIES = [
    ('Facultad de Ingeniería',              'ingenieria',              0),
    ('Facultad de Derecho',                 'derecho',                 1),
    ('Facultad de Comunicación',            'comunicacion',            2),
    ('Facultad de Ciencias Biomédicas',     'ciencias-biomedicas',     3),
    ('Facultad de Ciencias Empresariales',  'ciencias-empresariales',  4),
    ('Escuela de Gobierno',                 'gobierno',                5),
]


# ---------------------------------------------------------------------------
# Carreras: (nombre, slug, short, usa_cuatrimestres, faculty_slug)
# ---------------------------------------------------------------------------
CAREERS = [
    # Ingeniería
    ('Ingeniería Industrial',    'ingenieria-industrial',  'IND', True,  'ingenieria'),
    ('Ingeniería Biomédica',     'ingenieria-biomedica',   'BIO', False, 'ingenieria'),
    ('Ingeniería en Informática','ingenieria-informatica', 'INF', True,  'ingenieria'),
    # Derecho
    ('Abogacía',                 'abogacia',               'DER', True,  'derecho'),
    # Comunicación
    ('Comunicación',                                       'comunicacion-carrera',    'COM', False, 'comunicacion'),
    ('Diseño',                                             'diseno',                  'DIS', False, 'comunicacion'),
    ('Marketing con orientación en Comunicación y Diseño', 'marketing-com-dis',       'MCD', False, 'comunicacion'),
    # Ciencias Biomédicas
    ('Medicina',    'medicina',    'MED', False, 'ciencias-biomedicas'),
    ('Enfermería',  'enfermeria',  'ENF', True,  'ciencias-biomedicas'),
    ('Nutrición',   'nutricion',   'NUT', False, 'ciencias-biomedicas'),
    ('Psicología',  'psicologia',  'PSI', True,  'ciencias-biomedicas'),
    # Ciencias Empresariales
    ('Administración de Empresas', 'administracion-empresas', 'ADM', False, 'ciencias-empresariales'),
    ('Contador Público',           'contador-publico',        'CPN', False, 'ciencias-empresariales'),
    ('Economía Empresarial',       'economia-empresarial',    'ECO', False, 'ciencias-empresariales'),
    ('Marketing & Management',     'marketing-management',    'MKT', False, 'ciencias-empresariales'),
    ('Negocios Digitales',         'negocios-digitales',      'NDG', False, 'ciencias-empresariales'),
    # Escuela de Gobierno
    ('Ciencia Política',          'ciencia-politica',           'POL', True, 'gobierno'),
    ('Relaciones Internacionales','relaciones-internacionales', 'RRI', True, 'gobierno'),
]


# ---------------------------------------------------------------------------
# Planes de estudio.
# Industrial e Informática: clave (año, cuatrimestre).
# Biomédica: clave año (cuatrimestre = None).
# ---------------------------------------------------------------------------
INDUSTRIAL = {
    (1, 1): ['Análisis Matemático I', 'Álgebra I', 'Programación I',
             'Introducción a la Ingeniería', 'Filosofía General', 'Química General'],
    (1, 2): ['Análisis Matemático II', 'Álgebra II', 'Física Mecánica',
             'Química Aplicada', 'Introducción a las Operaciones'],
    (2, 1): ['Análisis Matemático III', 'Técnicas Digitales', 'Teología I',
             'Física Electricidad y Magnetismo', 'Ingeniería Gráfica y Diseño', 'Operaciones'],
    (2, 2): ['Análisis Matemático IV', 'Estadística I', 'Antropología',
             'Estática y Resistencia de los Materiales', 'Electrotecnia',
             'Taller de Excel Aplicado'],
    (3, 1): ['Termodinámica', 'Tecnología de Materiales',
             'Planificación y Control de la Producción', 'Máquinas Eléctricas',
             'Marketing y Emprendedurismo', 'Ética General', 'Estadística II',
             'Técnicas de Comunicación'],
    (3, 2): ['Contabilidad y Presupuestos', 'Mecánica de los Fluidos',
             'Mecánica Racional y Mecanismos', 'Ingeniería de Operaciones',
             'Taller de Análisis de Datos I', 'Moral Persona y Valores',
             'Sistemas de Control'],
    (4, 1): ['Investigación Operativa', 'Máquinas Térmicas',
             'Finanzas y Evaluación de Proyectos', 'Ética Profesional',
             'Gestión de Procesos Industriales'],
    (4, 2): ['Máquinas Herramientas', 'Cadena de Suministro', 'Ingeniería de Calidad',
             'Responsabilidad Social', 'Práctica Profesional Supervisada',
             'Química Industrial'],
    (5, 1): ['Instalaciones Industriales', 'Legal',
             'Economía y Evolución Socioeconómica', 'Gestión de Proyectos',
             'Proyecto Final de Carrera'],
    (5, 2): ['Mantenimiento y Confiabilidad Industrial',
             'Gestión Sostenible y Seguridad Industrial', 'Sistemas de Información',
             'Factor Humano', 'Proyecto Final de Carrera'],
}

INFORMATICA = {
    (1, 1): ['Análisis Matemático I', 'Álgebra I', 'Programación I',
             'Introducción a la Ingeniería', 'Filosofía General'],
    (1, 2): ['Análisis Matemático II', 'Álgebra II', 'Programación II',
             'Física General', 'Técnicas Digitales'],
    (2, 1): ['Arquitectura de Computadoras', 'Análisis Matemático III', 'Álgebra III',
             'Electricidad y Magnetismo', 'Algoritmos y Estructuras de Datos', 'Teología'],
    (2, 2): ['Cálculo Numérico', 'Estadística I', 'Matemática Discreta',
             'Análisis y Diseño de Algoritmos', 'Antropología', 'Sistemas Operativos',
             'Bases de Datos'],
    (3, 1): ['Teoría de la Empresa', 'Estadística II', 'Laboratorio I',
             'Redes de Comunicación de Datos', 'Electrónica Informática',
             'Ética General', 'Diseño de Sistemas'],
    (3, 2): ['Laboratorio II', 'Ingeniería de Sistemas', 'Lenguajes de Programación',
             'Diseño de Interacción', 'Moral Persona y Valores', 'Investigación Operativa'],
    (4, 1): ['Laboratorio III', 'Programación Concurrente',
             'Aseguramiento de la Calidad de Software', 'Seguridad Informática',
             'Ética Profesional', 'Inteligencia Artificial'],
    (4, 2): ['Sistemas Distribuidos', 'Comunicación Efectiva', 'Legal',
             'Responsabilidad Social'],
    (5, 1): ['Trabajo de Grado', 'Dirección de Proyectos', 'Microeconomía Aplicada'],
    (5, 2): ['Laboratorio IV', 'Factor Humano', 'Macroeconomía'],
}

BIOMEDICA = {
    1: ['Análisis Matemático I', 'Álgebra I', 'Introducción a la Filosofía',
        'Introducción a la Programación I', 'Química General',
        'Introducción a la Ingeniería', 'Análisis Matemático II',
        'Química Orgánica y Biológica', 'Álgebra II', 'Antropología',
        'Introducción a la Programación II', 'Física General'],
    2: ['Teología I', 'Análisis Matemático III', 'Anatomía y Biomecánica',
        'Probabilidad y Estadística', 'Termodinámica Clásica y Estadística',
        'Algoritmos y Estructuras de Datos', 'Biología Celular y Molecular',
        'Análisis Matemático IV', 'Bioestadística', 'Ópticas y Ondas',
        'Electricidad y Magnetismo', 'Medios de Representación', 'Bioinformática'],
    3: ['Ética General', 'Teoría de la Empresa',
        'Procesamiento de Imágenes y Señales Biomédicas', 'Fisiología I',
        'Bases de Datos', 'Electrónica Digital I', 'Electrotecnia', 'Fisiología II',
        'Electrónica Digital II', 'Teología II', 'Redes de Comunicación de Datos',
        'Electrónica Analógica', 'Modelado Análisis y Diseño de Sistemas Biomédicos'],
    4: ['Bioética', 'Ética Profesional', 'Legal', 'Biomateriales y Biosensores',
        'Fisiopatología', 'Laboratorio', 'Análisis Genómico',
        'Práctica Profesional Supervisada', 'Medicina Nuclear',
        'Instrumental Biomédico', 'Imágenes para Diagnóstico', 'Biología Estructural'],
    5: ['Contabilidad y Presupuestos', 'Finanzas y Evaluación de Proyectos',
        'Ingeniería de Rehabilitación', 'Inteligencia Artificial',
        'Organización Clínica y Hospitalaria', 'Dirección de Proyectos',
        'Trabajo de Grado'],
}


# ---------------------------------------------------------------------------
# Planes de Ciencias Biomédicas (sin cuatrimestres: clave = año)
# ---------------------------------------------------------------------------
MEDICINA = {
    1: ['Bioquímica I', 'Citología e Histología General', 'Anatomía I', 'Genética',
        'Relación Médico Paciente I', 'Teología I', 'Antropología'],
    2: ['Bioquímica II', 'Anatomía II', 'Histología Especial', 'Fisiología I', 'Fisiología II',
        'Bioestadística', 'Relación Médico Paciente II', 'Medicina Celular y Molecular',
        'Microbiología', 'Ética', 'Inmunología'],
    3: ['Epidemiología', 'Farmacología I', 'Teología II', 'Fisiopatología', 'Anatomía Patológica'],
    4: ['Diagnóstico por Imágenes', 'Otorrinolaringología', 'Metodología de la Investigación',
        'Medicina Interna I', 'Medicina Interna II', 'Toxicología', 'Farmacología II',
        'Cirugía', 'Urología', 'Nutrición', 'Cuestiones de Bioética'],
    5: ['Medicina Interna III', 'Pediatría', 'Ginecología', 'Obstetricia', 'Medicina Legal',
        'Enfermedades Infecciosas', 'Traumatología', 'Psiquiatría', 'Oftalmología',
        'Dermatología', 'Atención Primaria de la Salud', 'Gestión y Economía de la Salud',
        'Neurología', 'Salud Pública'],
    6: ['Internado Rotatorio', 'Medicina Crítica', 'Seminarios de Bioética'],
}

NUTRICION = {
    1: ['Química General y Biofísica', 'Histología', 'Fisiología Humana', 'Bioestadística I',
        'Habilidades de Comunicación Interpersonal', 'Antropología Filosófica',
        'Psicología y Alimentación', 'Bioquímica I'],
    2: ['Gestión de Servicios de Alimentación I', 'Nutrición Normal', 'Teología II',
        'Metodología de la Investigación I', 'Nutrición y Crecimiento',
        'Bromatología y Tecnología Alimentaria I', 'Técnica Dietética', 'Bioestadística II',
        'Bromatología y Tecnología Alimentaria II', 'Gestión de Servicios de Alimentación II',
        'Bioquímica II e Inmunología', 'Antropología Social', 'Teología I'],
    3: ['Epidemiología Nutricional', 'Fisiopatología y Dietoterapia del Adulto I',
        'Producción de Alimentos y Medioambiente', 'Nutrición y Envejecimiento',
        'Microbiología', 'Anatomía', 'Comercialización y Marketing en Alimentos',
        'Alimentación Vegetariana', 'Biología Celular y Molecular', 'Práctica Integradora I',
        'Técnica Dietoterápica', 'Fisiopatología y Dietoterapia del Adulto II',
        'Evaluación Alimentaria y Nutricional del Adulto', 'Salud Pública',
        'Cuestiones de Bioética', 'Práctica Integradora II',
        'Taller Metodología de la Investigación I'],
    4: ['Genética y Nutrigenómica', 'Nutrición Comunitaria', 'Metodología de la Investigación II',
        'Práctica Integradora III', 'Soporte Nutricional', 'Ética y Nutrición',
        'Sistema de Calidad', 'Alimentación en el Deportista',
        'Fisiopatología y Dietoterapia Pediátrica', 'Taller Trabajo Integrador Final I',
        'Comunicación en Alimentación y Nutrición',
        'Interacción entre Fármacos Alimentos y Hierbas'],
    5: ['Prácticas Profesionales Supervisadas', 'Taller Trabajo Integrador Final II'],
}

# Psicología y Enfermería usan cuatrimestres: clave = (año, cuatrimestre)
PSICOLOGIA = {
    (1, 1): ['Historia de la Psicología', 'Sociología', 'Teología I',
             'Neuropsicología General I', 'Historia de las Ideas Filosóficas I',
             'Historia de las Ideas Filosóficas II', 'Psicología General',
             'Estadística Descriptiva'],
    (1, 2): ['Neuropsicología General II', 'Antropología Filosófica I',
             'Psicología del Desarrollo Humano I'],
    (2, 1): ['Teorías Psicológicas I', 'Psicología Social', 'Estadística Inferencial',
             'Metodología de la Investigación Cuantitativa', 'Antropología Filosófica II'],
    (2, 2): ['Antropología Cultural', 'Teorías Psicológicas II', 'Psicología de la Personalidad I',
             'Psicometría', 'Metodología de la Investigación Cualitativa',
             'Psicología del Desarrollo Humano II'],
    (3, 1): ['Psicopatología General', 'Psicología de los Vínculos Familiares',
             'Técnicas de Evaluación Psicológica I', 'Psicología Educacional',
             'Psicología de la Personalidad II', 'Teología II'],
    (3, 2): ['Filosofía del Conocimiento y Epistemología', 'Psicopatología Adultos',
             'Psicopatología Infanto Juvenil', 'Técnicas de Evaluación Psicológica II',
             'Psicología Laboral', 'Psicología del Aprendizaje'],
    (4, 1): ['Recursos Humanos', 'Proceso de Orientación Vocacional',
             'Diagnóstico Clínico Adultos', 'Diagnóstico Clínico Infanto Juvenil',
             'Bases Biológicas de la Terapia', 'Ética'],
    (4, 2): ['Psicología Clínica Cognitivo Comportamental', 'Psicología Clínica Psicodinámica',
             'Psicología Clínica Sistémica', 'Neuropsicología Clínica'],
    (5, 1): ['Deontología Profesional', 'Psicología Jurídica',
             'Intervenciones Sociales y Comunitarias',
             'Salud Pública Sistemas y Políticas de Salud', 'Trabajo de Integración Final'],
}

ENFERMERIA = {
    (1, 1): ['Desarrollo Teórico de la Enfermería', 'Introducción a la Filosofía',
             'Psicología del Desarrollo', 'Anatomía y Fisiología I', 'Bioquímica',
             'Fundamentos de Enfermería y Seguridad del Paciente I',
             'Enfermería Comunitaria I', 'Antropología', 'Teología I'],
    (1, 2): ['Anatomía y Fisiología II'],
    (2, 1): ['Fundamentos de Enfermería y Seguridad del Paciente II',
             'Introducción a la Sociología', 'Microbiología y Parasitología',
             'Nutrición y Dietoterapia', 'Farmacología', 'Bioestadística',
             'Enfermería del Adulto y Adulto Mayor', 'Enfermería Comunitaria II',
             'Enfermería en Salud Mental I', 'Ética', 'Epidemiología'],
    (3, 1): ['Enfermería Materno Infantil', 'Enfermería Comunitaria III',
             'Enfermería en Salud Mental II', 'Deontología Profesional',
             'Metodología de la Investigación', 'Enfermería del Niño y del Adolescente',
             'Principios de Administración de los Servicios de Salud',
             'Investigación en Enfermería I', 'Teología II', 'Práctica Integrada I'],
    (4, 1): ['Enfermería del Adulto y Adulto Mayor en Estado Crítico',
             'Enfermería Comunitaria IV', 'Administración de los Servicios de Enfermería',
             'Investigación en Enfermería II', 'Filosofía', 'Enfermería Comunitaria V',
             'Liderazgo y Gestión en las Organizaciones', 'Taller de Investigación I',
             'Bioética', 'Sociología'],
    (5, 1): ['Enfermería del Niño y del Adolescente en Estado Crítico',
             'Liderazgo y Gestión en Enfermería', 'Educación en Enfermería',
             'Taller de Investigación II', 'Práctica Integrada II'],
}


# ---------------------------------------------------------------------------
# Planes de Derecho y Comunicación
# Abogacía usa Quarters: clave (año, cuatrimestre); años 3-5 sin división → (año, None)
# Las demás: clave año (sin cuatrimestre)
# ---------------------------------------------------------------------------
ABOGACIA = {
    (1, 1): ['Teoría del Derecho', 'Derecho Privado I Parte General y Acto Jurídico',
             'Expresión y Argumentación', 'Taller de Metodología de la Investigación Jurídica I'],
    (1, 2): ['Derecho Privado II Personas', 'Filosofía General y Antropología',
             'Fundamentos del Cristianismo'],
    (2, 1): ['Derecho Penal I Parte General', 'Derecho Romano e Instituciones Contemporáneas',
             'Ciencia Política'],
    (2, 2): ['Derecho de las Obligaciones',
             'Derecho Constitucional I Teoría de la Constitución y Organización del Estado',
             'Fundamentos de Ética', 'Derecho de Daños',
             'Derecho Constitucional II Sistema de Derechos Humanos',
             'Derecho Penal II Delitos contra Bienes Individuales', 'Moral Persona y Valores',
             'Derecho Internacional Público',
             'Derecho Penal III Delitos contra el Estado y la Sociedad', 'Economía'],
    (3, None): ['Derecho de los Contratos I Parte General', 'Derecho Procesal Penal',
                'Derecho del Trabajo y de la Seguridad Social',
                'Derecho de los Contratos II Parte Especial',
                'Derecho Ambiental y de los Recursos Naturales',
                'Derecho del Consumidor y Defensa de la Competencia',
                'Derecho Procesal Civil', 'Derecho Societario', 'Ética Social',
                'Seminario de Historia del Derecho',
                'Taller de Metodología de la Investigación Jurídica II'],
    (4, None): ['Derechos Reales', 'Derecho de la Integración', 'Arbitraje y Litigación Oral',
                'Clínica Jurídica I',
                'Derecho Administrativo I Teoría General Acto y Procedimiento',
                'Derecho de los Títulos Valores', 'Derecho de Familia',
                'Seminario de Introducción a la Sociología',
                'Derecho Administrativo II Actividad y Responsabilidad del Estado',
                'Derecho Concursal', 'Clínica Jurídica II'],
    (5, None): ['Derecho Internacional Privado', 'Derecho Sucesorio y Planificación Patrimonial',
                'Derecho Tributario', 'Common Law Institutions', 'Filosofía del Derecho',
                'Análisis Económico del Derecho', 'Ética y Responsabilidad Profesional'],
}

COMUNICACION_PLAN = {
    1: ['Introducción a la Filosofía', 'Contenidos Culturales Contemporáneos',
        'Historia Universal Contemporánea', 'Historia y Cultura de la Comunicación',
        'Apreciación Visual y Estética', 'Comunicación 360', 'Taller de Expresión Oral',
        'Lengua y Comunicación I', 'Lengua y Comunicación II', 'Introducción al Periodismo'],
    2: ['Antropología', 'Teoría de la Comunicación', 'Teología I', 'Imagen Corporativa',
        'Historia Argentina y Latinoamericana', 'Taller de Herramientas Digitales de Diseño',
        'Taller de Producción Sonora', 'Tecnologías de la Información y la Comunicación',
        'Narración Audiovisual', 'Diseño', 'Producción Discursiva', 'Lenguaje Sonoro'],
    3: ['Deontología', 'Análisis e Información de la Sociedad', 'Análisis Internacional',
        'Teología II', 'Análisis e Información de la Política', 'Análisis del Discurso',
        'Epistemología de la Comunicación', 'Géneros y Estilos Informativos',
        'Producción Audiovisual', 'Taller de Redacción Multimodal',
        'Taller de Realización Audiovisual', 'Seminario de Inserción Laboral'],
    4: ['Sociología de la Comunicación', 'Comunicación para la Gestión del Cambio',
        'Gestión de Negocios en la Industria de Contenidos', 'Comunicación Publicitaria',
        'Gestión y Diseño de Negocios', 'Gestión de la Comunicación en las Organizaciones',
        'Economía', 'Marketing', 'Asuntos Públicos', 'Derecho de la Información',
        'Seminario de Herramientas Digitales de Gestión y Administración',
        'Géneros y Estilos Creativos', 'Proyecto Profesional'],
}

DISENO = {
    1: ['Introducción Proyectual', 'Hacer Diseño I', 'Pensar Diseño I', 'Hacer Diseño II',
        'Pensar Diseño II', 'Tradiciones y Tendencias Culturales I', 'Sistema I',
        'Maquetas y Prototipos', 'Sistema II', 'Procesos y Materiales I',
        'Recursos Expresivos I', 'Recursos Expresivos II'],
    2: ['Hacer Diseño III', 'Pensar Diseño III', 'Hacer Diseño IV', 'Pensar Diseño IV',
        'Antropología', 'Tradiciones y Tendencias Culturales II', 'Teología I',
        'Tradiciones y Tendencias Culturales III', 'Recursos Expresivos III', 'Producción I',
        'Recursos Expresivos IV', 'Diseño Estratégico I', 'Diseño Estratégico II'],
    3: ['Diseño y Sistema I', 'Diseño y Sistema II', 'Comunicación', 'Estética',
        'Producción II', 'Diseño de la Experiencia', 'Procesos y Materiales II',
        'Gestión I', 'Gestión II'],
    4: ['Diseño y Territorio I', 'Diseño y Territorio II', 'Teología II', 'Deontología',
        'Producción III', 'Procesos y Materiales III', 'Gestión III', 'Emprendimientos',
        'Proyecto'],
}

MARKETING_COM_DIS = {
    1: ['Antropología', 'Introducción a la Filosofía',
        'Herramientas Digitales de Diseño y de Negocios',
        'Lenguajes Multimedias y Mundos Virtuales', 'Diseño Estratégico',
        'Introducción a la Creatividad', 'Introducción al Marketing', 'Comunicación 360°',
        'Introducción a los Lenguajes Multimedia', 'Tradiciones y Tendencias Culturales',
        'Historia de la Comunicación y el Marketing', 'Taller de Expresión Oral',
        'Lengua y Comunicación'],
    2: ['Historia y Análisis de Tendencias Socioculturales Latinoamericanas', 'Teología',
        'Tecnologías e Innovación', 'Introducción al Business Intelligence',
        'Matemática Financiera', 'Introducción a Álgebra y Análisis Matemático',
        'Investigación de Mercados', 'Introducción a la Economía', 'Imagen Corporativa',
        'Estrategia de Producto y Marca', 'Marketing Audiovisual', 'Teoría de la Comunicación'],
    3: ['Teología Moral', 'Costos', 'Gestión y Diseño de Negocios', 'Métodos Cuantitativos',
        'Comunicación Marketing e Información', 'Estadística', 'Marketing de Servicios',
        'Introducción al Comportamiento Humano',
        'Análisis de Tendencias Socioculturales Internacionales', 'Marketing Metrics',
        'Comunicación Publicitaria'],
    4: ['Ética Empresa y Sociedad', 'Logística y Operaciones', 'Digital Methodologies',
        'Diseño de Experiencias Interactivas', 'Marketing e Innovación Social',
        'Entrepreneurship', 'Marketing y Relaciones Públicas',
        'Dirección Comercial y Marketing', 'Estrategia de Precios',
        'Mkt y Comunicación en las Organizaciones',
        'Comunicación para la Gestión del Cambio',
        'Gestión de Negocios en la Industria de Contenidos'],
}


# ---------------------------------------------------------------------------
# Planes de Ciencias Empresariales (sin cuatrimestres: clave = año)
# ---------------------------------------------------------------------------
ADMINISTRACION = {
    1: ['Administración I', 'Historia Económica y Social', 'Introducción Contabilidad',
        'Contabilidad Básica', 'Antropología', 'Filosofía', 'Álgebra y Geometría',
        'Análisis Matemático I'],
    2: ['Comercialización', 'Matemática Financiera', 'Economía General', 'Microeconomía',
        'Estados Contables', 'Comportamiento Humano', 'Estadística I', 'Derecho Empresario I',
        'Análisis Matemático II', 'Teología I'],
    3: ['IT y Business Intelligence', 'Macroeconomía', 'Costos', 'Finanzas Corporativas',
        'Métodos Cuantitativos', 'Fundamentos Tributación', 'Teología II',
        'Derecho Empresario II', 'Doctrina Social'],
    4: ['Entrepreneurship', 'Dirección Estratégica', 'Control de Gestión', 'Ética',
        'Management II', 'Dirección de Personas', 'Economía de Empresa y Estrategia de Mercado',
        'Gestión Comercial y Estrategia de Ventas'],
}

ECONOMIA_EMP = {
    1: ['Administración I', 'Historia Económica y Social', 'Introducción Contabilidad',
        'Contabilidad Básica', 'Álgebra y Geometría', 'Análisis Matemático I',
        'Derecho Empresario I', 'Antropología', 'Filosofía'],
    2: ['Economía General', 'Microeconomía I', 'Estadística I', 'Matemática Financiera',
        'Estadística II', 'Derecho Empresario II', 'Teología I', 'Análisis Matemático II',
        'Estados Contables', 'Introducción al Pensamiento Económico', 'Comercialización',
        'Comportamiento Humano'],
    3: ['Econometría', 'Microeconomía II', 'Macroeconomía', 'Matemática para Economistas',
        'Finanzas Corporativas', 'Costos', 'Fundamentos Tributación', 'Teología II',
        'Doctrina Social', 'Modelos Cuantitativos para Decisiones'],
    4: ['Economía de Empresa y Mercado', 'Entrepreneurship', 'Dirección Estratégica',
        'Finanzas de Mercado', 'Control de Gestión', 'Ética',
        'Desarrollo Económico y Políticas Públicas', 'Big Data'],
}

MARKETING_MGMT = {
    1: ['Introducción a la Comercialización Digital', 'Administración I',
        'Introducción Contabilidad', 'Contabilidad Básica', 'Historia Económica y Social',
        'Antropología', 'Filosofía', 'Álgebra y Geometría', 'Análisis Matemático I'],
    2: ['Estrategia de Producto y Marca', 'Introducción al Conocimiento del Consumidor',
        'Economía General', 'Matemática Financiera', 'Comportamiento Humano',
        'Derecho Empresario I', 'Estadística I', 'Estados Contables', 'Teología I',
        'Análisis Contable II', 'Negocios Digitales y Exponential Technologies',
        'Fundamentos de Programación'],
    3: ['Fundamentos de Comunicación Publicitaria', 'Marketing Servicios',
        'Estrategia de Precios', 'Business Intelligence y Data Visualization', 'Macroeconomía',
        'Finanzas Corporativas', 'Costos', 'Teología II', 'Doctrina Social',
        'Product Development', 'Comunicación Digital', 'Canales de Distribución y Trade',
        'Ecommerce', 'Marketing Metrics', 'Negocios Cloud'],
    4: ['Inteligencia Artificial y Ciencia de Datos', 'Entrepreneurship',
        'Dirección Estratégica', 'Dirección Comercial', 'Control de Gestión', 'Ética'],
}

CONTADOR_PUB = {
    1: ['Administración I', 'Historia Económica y Social', 'Introducción Contabilidad',
        'Contabilidad Básica', 'Antropología', 'Filosofía', 'Álgebra y Geometría',
        'Análisis Matemático I'],
    2: ['Comercialización', 'Matemática Financiera', 'Economía General', 'Microeconomía',
        'Estados Contables', 'Comportamiento Humano', 'Estadística I', 'Derecho Empresario I',
        'Análisis Matemático II', 'Teología I', 'Management II'],
    3: ['IT y Business Intelligence', 'Macroeconomía', 'Costos', 'Estados Contables II',
        'Fundamentos Tributación', 'Métodos Cuantitativos', 'Derecho Público', 'Teología II',
        'Derecho Empresario II', 'Doctrina Social', 'Finanzas Corporativas'],
    4: ['Auditoría I', 'Impuestos I', 'Dirección Estratégica', 'Control de Gestión',
        'Contabilidad Superior', 'Contabilidad Aplicada a Actividades Específicas',
        'Derecho Empresario III', 'Ética General', 'Entrepreneurship',
        'Economía de Empresa y Estrategia de Mercado', 'Análisis de Estados Financieros'],
    5: ['Concursos y Quiebras', 'Auditoría II', 'Impuestos II', 'Contabilidad Internacional'],
}

NEGOCIOS_DIG = {
    1: ['Digital Methodologies', 'User Experience', 'Administración I',
        'Introducción Contabilidad', 'Contabilidad Básica', 'Antropología',
        'Historia Económica y Social', 'Filosofía', 'Álgebra y Geometría',
        'Análisis Matemático I'],
    2: ['Product Development', 'Programación I', 'Economía General', 'Microeconomía I',
        'Matemática Financiera', 'Estadística I', 'Comportamiento Humano', 'Estados Contables',
        'Derecho Empresario I', 'Teología I', 'Análisis Matemático II'],
    3: ['Product Management I', 'Product Management II', 'Comercialización', 'Macroeconomía',
        'Costos', 'Finanzas Corporativas', 'Teología II', 'Doctrina Social',
        'Negocios Digitales y Exponential Technologies', 'Fintech y Blockchain',
        'IT y Business Intelligence', 'Programación en los Negocios',
        'Programación Avanzada y Arquitecturas de Software', 'Big Data Aplicada al Negocio',
        'Negocios Cloud', 'Gestión Comercial y Estrategia de Ventas'],
    4: ['Inteligencia Artificial y Ciencia de Datos', 'Entrepreneurship', 'Control de Gestión',
        'Dirección Estratégica', 'Ética'],
}


# ---------------------------------------------------------------------------
# Planes de la Escuela de Gobierno (cuatrimestres mixtos: años 3-4 sin división)
# ---------------------------------------------------------------------------
CIENCIA_POLITICA = {
    (1, 1): ['Introducción a la Ciencia Política', 'Historia del Mundo Contemporáneo',
             'Expresión Oral y Escrita', 'Teoría del Derecho', 'Sociología',
             'Introducción a las Políticas Públicas'],
    (1, 2): ['Introducción a las Relaciones Internacionales', 'Filosofía y Antropología',
             'Economía I', 'Teología I'],
    (2, 1): ['Historia del Pensamiento Político I',
             'Historia de los Procesos Políticos Argentinos y Latinoamericanos',
             'Comunicación Política', 'Derecho Constitucional Argentino', 'Ciencia Política I',
             'Teoría de las Relaciones Internacionales', 'Ética y Metafísica', 'Economía II',
             'Teología II'],
    (2, 2): ['Contenidos Culturales Contemporáneos', 'Estructura del Gobierno y la Administración'],
    (3, None): ['Historia del Pensamiento Político II', 'Sistemas Políticos Comparados',
                'Organizaciones de la Sociedad Civil', 'Derecho Internacional Público',
                'Ciencia Política II', 'Análisis Internacional',
                'Desarrollo Humano Económico y Social', 'Economía III',
                'Doctrina Social de la Iglesia', 'Geografía Política y Económica',
                'Metodología de la Investigación Social I',
                'Metodología de la Investigación Social II'],
    (4, None): ['Redacción Documental Legislativa', 'Diseño y Gestión de Políticas Públicas',
                'Programación para Ciencias Sociales', 'Taller de Trabajo Final de Grado'],
}

RELACIONES_INT = {
    (1, 1): ['Introducción a la Ciencia Política', 'Sociología',
             'Historia del Mundo Contemporáneo', 'Expresión Oral y Escrita y Argumentación',
             'Teoría del Derecho'],
    (1, 2): ['Introducción a las Políticas Públicas',
             'Introducción a las Relaciones Internacionales', 'Economía I',
             'Filosofía y Antropología', 'Teología I'],
    (2, 1): ['Historia de los Procesos Políticos Argentinos y Latinoamericanos',
             'Historia del Pensamiento Político I', 'Derecho Constitucional Argentino',
             'Ética y Metafísica', 'Teología II'],
    (2, 2): ['Teoría de las Relaciones Internacionales', 'Ciencia Política I',
             'Gobierno y Administración de la República Argentina', 'Economía II',
             'Contenidos Culturales Contemporáneos'],
    (3, 1): ['Organizaciones de la Sociedad Civil', 'Historia del Pensamiento Político II',
             'Ciencia Política II', 'Metodología de la Investigación Social I', 'Economía III',
             'Derecho Internacional Público'],
    (3, 2): ['Sistemas Políticos Comparados', 'Análisis Internacional',
             'Desarrollo Humano Económico y Social en Argentina y Latinoamérica',
             'Geografía Política y Económica Argentina',
             'Metodología de la Investigación Social II', 'Doctrina Social de la Iglesia'],
    (4, 1): ['Derecho Consular', 'Política Exterior', 'Conflictos Internacionales y Seguridad',
             'Estrategia y Negociación Internacional',
             'Temas de Gobernanza Global en el Siglo XXI',
             'Programación para Ciencias Sociales', 'Taller de Trabajo Final de Grado',
             'Técnica Documental y Legislativa'],
}


# ---------------------------------------------------------------------------
# Materias compartidas: existen UNA sola vez y se asocian a varias carreras.
# Cualquier materia cuyo nombre NO esté acá se crea por carrera (registro
# independiente), aunque el nombre coincida con el de otra carrera.
# ---------------------------------------------------------------------------
SHARED_NAMES = {
    'Análisis Matemático I', 'Análisis Matemático II', 'Análisis Matemático III',
    'Álgebra I', 'Álgebra II',
    'Introducción a la Ingeniería',
    'Química General',
    'Filosofía General',
    'Antropología',
    'Estadística I',
    'Ética General',
    'Electrotecnia',
    'Algoritmos y Estructuras de Datos',
    'Electricidad y Magnetismo',
    'Bases de Datos',
    'Teoría de la Empresa',
    'Redes de Comunicación de Datos',
    'Teología I',
    'Moral Persona y Valores',
    'Ética Profesional',
    'Legal',
    'Inteligencia Artificial',
    'Dirección de Proyectos',
    'Contabilidad y Presupuestos',
    'Finanzas y Evaluación de Proyectos',
    'Investigación Operativa',
    'Factor Humano',
    'Programación Concurrente',
}

# Materias compartidas DENTRO de Ciencias Empresariales (slug sufijo -ce).
# Aisladas de otras facultades; quien no esté aquí recibe sufijo de carrera.
EMPRESARIALES_SHARED_NAMES = {
    'Administración I', 'Historia Económica y Social', 'Introducción Contabilidad',
    'Contabilidad Básica', 'Antropología', 'Filosofía', 'Álgebra y Geometría',
    'Análisis Matemático I', 'Economía General', 'Matemática Financiera',
    'Comportamiento Humano', 'Estadística I', 'Estados Contables', 'Derecho Empresario I',
    'Análisis Matemático II', 'Teología I', 'Macroeconomía', 'Costos',
    'Finanzas Corporativas', 'Teología II', 'Doctrina Social', 'Entrepreneurship',
    'Dirección Estratégica', 'Control de Gestión', 'Ética',
    'IT y Business Intelligence', 'Fundamentos Tributación', 'Derecho Empresario II',
    'Microeconomía', 'Inteligencia Artificial y Ciencia de Datos', 'Product Development',
    'Negocios Digitales y Exponential Technologies', 'Negocios Cloud',
    'Gestión Comercial y Estrategia de Ventas',
}

# Materias compartidas DENTRO de la Escuela de Gobierno (slug sufijo -gov).
GOBIERNO_SHARED_NAMES = {
    'Introducción a la Ciencia Política', 'Historia del Mundo Contemporáneo',
    'Expresión Oral y Escrita', 'Teoría del Derecho', 'Sociología',
    'Introducción a las Políticas Públicas', 'Introducción a las Relaciones Internacionales',
    'Filosofía y Antropología', 'Economía I', 'Teología I',
    'Historia del Pensamiento Político I',
    'Historia de los Procesos Políticos Argentinos y Latinoamericanos',
    'Derecho Constitucional Argentino', 'Ciencia Política I',
    'Teoría de las Relaciones Internacionales', 'Ética y Metafísica', 'Economía II',
    'Teología II', 'Contenidos Culturales Contemporáneos',
    'Historia del Pensamiento Político II', 'Sistemas Políticos Comparados',
    'Organizaciones de la Sociedad Civil', 'Derecho Internacional Público',
    'Ciencia Política II', 'Análisis Internacional', 'Economía III',
    'Doctrina Social de la Iglesia', 'Metodología de la Investigación Social I',
    'Metodología de la Investigación Social II', 'Programación para Ciencias Sociales',
    'Taller de Trabajo Final de Grado',
}

# Sufijo de slug para materias compartidas dentro de una facultad.
FACULTY_SLUG_SUFFIX = {
    'ciencias-empresariales': 'ce',
    'gobierno': 'gov',
}


def _normalize_plan(plan, uses_cuatri):
    """Devuelve lista de (year, cuatrimestre, name) a partir de un plan."""
    out = []
    if uses_cuatri:
        for (year, cuatri), names in plan.items():
            for name in names:
                out.append((year, cuatri, name))
    else:
        for year, names in plan.items():
            for name in names:
                out.append((year, None, name))
    return out


def seed_plan():
    # --- Facultades ---
    faculties = {}
    for name, slug, order in FACULTIES:
        faculty = Faculty.query.filter_by(slug=slug).first()
        if not faculty:
            faculty = Faculty(name=name, slug=slug, order=order)
            db.session.add(faculty)
        faculties[slug] = faculty
    db.session.flush()

    # --- Carreras ---
    careers = {}
    for i, (name, slug, short, uses_cuatri, faculty_slug) in enumerate(CAREERS):
        career = Career.query.filter_by(slug=slug).first()
        if not career:
            career = Career(name=name, slug=slug, short=short, order=i,
                            has_cuatrimestres=uses_cuatri)
            db.session.add(career)
        if career.faculty_id is None:
            career.faculty_id = faculties[faculty_slug].id
        careers[slug] = career
    db.session.flush()

    plans = {
        'ingenieria-industrial':  INDUSTRIAL,
        'ingenieria-informatica': INFORMATICA,
        'ingenieria-biomedica':   BIOMEDICA,
        'medicina':               MEDICINA,
        'nutricion':              NUTRICION,
        'psicologia':             PSICOLOGIA,
        'enfermeria':             ENFERMERIA,
        'abogacia':               ABOGACIA,
        'comunicacion-carrera':   COMUNICACION_PLAN,
        'diseno':                 DISENO,
        'marketing-com-dis':      MARKETING_COM_DIS,
        'administracion-empresas': ADMINISTRACION,
        'economia-empresarial':    ECONOMIA_EMP,
        'marketing-management':    MARKETING_MGMT,
        'contador-publico':        CONTADOR_PUB,
        'negocios-digitales':      NEGOCIOS_DIG,
        'ciencia-politica':          CIENCIA_POLITICA,
        'relaciones-internacionales': RELACIONES_INT,
    }

    # Facultades con aislamiento total (todos los slugs sufijados por carrera).
    FORCE_UNIQUE_FACULTY = {'ciencias-biomedicas', 'derecho', 'comunicacion'}

    # Facultades con compartición interna (sufijo de facultad para compartidas).
    FACULTY_INTERNAL_SHARED = {
        'ciencias-empresariales': EMPRESARIALES_SHARED_NAMES,
        'gobierno':               GOBIERNO_SHARED_NAMES,
    }

    subjects_created = links_created = 0

    def _compute_slug(subj_name, career_short, faculty_slug):
        base = slugify(subj_name)
        if faculty_slug in FORCE_UNIQUE_FACULTY:
            return f'{base}-{career_short.lower()}'
        if faculty_slug in FACULTY_INTERNAL_SHARED:
            if subj_name in FACULTY_INTERNAL_SHARED[faculty_slug]:
                return f'{base}-{FACULTY_SLUG_SUFFIX[faculty_slug]}'
            return f'{base}-{career_short.lower()}'
        # Ingeniería: compartición global via SHARED_NAMES
        return base if subj_name in SHARED_NAMES else f'{base}-{career_short.lower()}'

    def get_or_create_subject(subj_name, subj_slug):
        nonlocal subjects_created
        subject = Subject.query.filter_by(slug=subj_slug).first()
        if subject is None:
            subject = Subject(name=subj_name, slug=subj_slug)
            db.session.add(subject)
            db.session.flush()
            subjects_created += 1
        return subject

    for name, slug, short, uses_cuatri, faculty_slug in CAREERS:
        if slug not in plans:
            continue
        career = careers[slug]
        for year, cuatri, subj_name in _normalize_plan(plans[slug], uses_cuatri):
            subj_slug = _compute_slug(subj_name, short, faculty_slug)
            subject = get_or_create_subject(subj_name, subj_slug)

            exists = CareerSubject.query.filter_by(
                career_id=career.id, subject_id=subject.id,
                year=year, cuatrimestre=cuatri
            ).first()
            if not exists:
                db.session.add(CareerSubject(
                    career=career, subject=subject, year=year, cuatrimestre=cuatri
                ))
                links_created += 1

    db.session.flush()
    return subjects_created, links_created


def ensure_categories():
    """
    Garantiza la estructura fija de categorías en TODAS las materias.
    Las materias nuevas ya las reciben por el listener after_insert; esto es un
    respaldo idempotente para materias que pudieran haber quedado sin ellas
    (p. ej. bases creadas antes de esta feature).
    """
    created = 0
    for subject in Subject.query.all():
        if subject.categories.count() > 0:
            continue
        for order, (slug, name, children) in enumerate(CATEGORY_TREE):
            parent = Category(subject_id=subject.id, name=name, slug=slug, order=order)
            db.session.add(parent)
            db.session.flush()
            created += 1
            for corder, (cslug, cname) in enumerate(children):
                db.session.add(Category(subject_id=subject.id, parent_id=parent.id,
                                        name=cname, slug=cslug, order=corder))
                created += 1
    return created


def _ensure_schema():
    """
    Lleva el esquema al día vía Alembic (flask db upgrade).
    El esquema lo gestionan las migraciones en migrations/, NO db.create_all().

    - Base nueva/vacía: aplica todas las migraciones y crea las tablas.
    - Base ya versionada por Alembic: aplica solo las migraciones pendientes.
    - Base preexistente SIN versionar (transición inicial): se detiene y pide
      ejecutar `flask db stamp head` una vez, para no intentar recrear tablas.
    """
    from sqlalchemy import inspect
    from flask_migrate import upgrade

    tables = inspect(db.engine).get_table_names()
    if tables and 'alembic_version' not in tables:
        print('⚠ La base ya tiene tablas pero no está versionada por Alembic.')
        print('  Ejecutá UNA sola vez para marcar el esquema actual como base:')
        print('      flask --app run db stamp head')
        print('  y volvé a correr este script.')
        raise SystemExit(1)

    upgrade()
    print('Esquema al día (flask db upgrade).')


def init():
    app = create_app()
    with app.app_context():
        _ensure_schema()

        admin_email = os.environ.get('ADMIN_EMAIL', 'admin@austral.edu.ar')
        admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
        if not User.query.filter_by(email=admin_email).first():
            admin = User(name='Admin', email=admin_email, is_admin=True, is_verified=True)
            admin.set_password(admin_password)
            db.session.add(admin)
            print(f'Admin creado: {admin_email}')
        else:
            print('Admin ya existe.')

        subjects_created, links_created = seed_plan()
        db.session.commit()

        cats_backfilled = ensure_categories()
        db.session.commit()

        print(f'Facultades: {Faculty.query.count()}')
        print(f'Carreras: {Career.query.count()}')
        print(f'Materias creadas: {subjects_created} (total: {Subject.query.count()})')
        print(f'Asociaciones carrera-materia creadas: {links_created} (total: {CareerSubject.query.count()})')
        print(f'Categorías (backfill manual): {cats_backfilled} (total: {Category.query.count()})')
        print('Listo.')


if __name__ == '__main__':
    init()
