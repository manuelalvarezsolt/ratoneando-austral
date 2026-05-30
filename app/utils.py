import re
import os
from flask import current_app


def slugify(text):
    text = text.lower().strip()
    replacements = {'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ü': 'u', 'ñ': 'n'}
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')


def is_austral_email(email):
    email = email.lower().strip()
    return any(email.endswith(f'@{domain}') for domain in current_app.config['AUSTRAL_DOMAINS'])


def allowed_file(filename):
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']
    )


def save_uploaded_file(file, subject_slug='', category_slug=''):
    """
    Guarda el archivo y devuelve la ruta relativa a static/.
    Estructura en disco: uploads/<subject_slug>/<category_slug>/<uuid>.<ext>
    """
    import uuid
    ext = file.filename.rsplit('.', 1)[-1].lower()
    safe_name = f'{uuid.uuid4().hex}.{ext}'
    parts = [p for p in (subject_slug, category_slug) if p]
    subfolder = os.path.join(*parts) if parts else ''
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], subfolder)
    os.makedirs(folder, exist_ok=True)
    file.save(os.path.join(folder, safe_name))
    rel = os.path.join('uploads', subfolder, safe_name) if subfolder else os.path.join('uploads', safe_name)
    return rel.replace('\\', '/')


def delete_uploaded_file(file_path):
    """Elimina el archivo físico del disco si existe (path relativo a static/)."""
    if not file_path:
        return
    full = os.path.join(current_app.root_path, 'static', file_path)
    try:
        os.remove(full)
    except OSError:
        pass
