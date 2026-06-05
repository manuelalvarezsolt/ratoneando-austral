"""Constantes compartidas entre módulos de la app."""

# Extensiones permitidas para subida de archivos (admin, moderador y alumnos).
# Fuente única: importar desde acá, no redefinir en cada módulo.
UPLOAD_ALLOWED_EXTENSIONS = [
    'pdf', 'doc', 'docx', 'ppt', 'pptx',
    'txt', 'jpg', 'jpeg', 'png', 'xlsx',
]
