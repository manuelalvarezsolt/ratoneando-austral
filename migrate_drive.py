"""
migrate_drive.py
----------------
Migra el contenido del Drive de Ratoneando Ingeniería a la plataforma.

Autenticación: service account OAuth 2.0 (credentials.json en la raíz del proyecto).
Dependencias extra (instalar si no están):
    pip install google-auth google-auth-httplib2

Uso:
    python migrate_drive.py           # migración completa
    python migrate_drive.py --test    # modo prueba: solo loguea, no descarga ni guarda
"""

import io
import os
import re
import sys
import json
import uuid
import argparse
import unicodedata
import difflib
from pathlib import Path
from datetime import datetime

# Forzar UTF-8 en stdout (igual que drive_explorer.py)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from app import create_app, db
from app.models import Subject, Category, Resource, User
from app.utils import slugify


# ── Configuración ──────────────────────────────────────────────────────────────
CREDENTIALS_FILE = 'credentials.json'
SCOPES           = ['https://www.googleapis.com/auth/drive.readonly']
ROOT_ID          = '1WN03K1GkaWITw93C088wgJfm8lx-ttxx'
# Detección de carpetas de año: ordinal numérico o en palabras + "año" en cualquier forma
_ANO_RE = re.compile(r'\bano\b')
_YEAR_PATTERNS = [
    (1, re.compile(r'\b(1(er?)?|primer|uno)\b')),
    (2, re.compile(r'\b(2(do?)?|segundo|dos)\b')),
    (3, re.compile(r'\b(3(er?)?|tercer[ao]?|tres)\b')),
    (4, re.compile(r'\b(4(to?)?|cuarto|cuatro)\b')),
    (5, re.compile(r'\b(5(to?)?|quinto|cinco)\b')),
]

# Detección de carpetas de cuatrimestre: capa intermedia entre año y materia
_CUATRI_RE = re.compile(r'\bcuatrimestre\b')
_CUATRI_PATTERNS = [
    (1, re.compile(r'\b(1(er?)?|primer|uno)\b')),
    (2, re.compile(r'\b(2(do?)?|segundo|dos)\b')),
]
LOG_FILE    = 'migration_log.json'
STATIC_DIR  = Path('app/static')
FOLDER_MIME = 'application/vnd.google-apps.folder'
ALLOWED_EXT = {'.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png', '.xlsx'}


# ── Reglas de clasificación (se evalúan en orden; primera que matchea gana) ────
CATEGORY_RULES = [
    ('parciales',            ['parcial']),
    ('finales',              ['final', 'examen final']),
    ('integradores',         ['integrador']),
    ('ejercicios-resueltos', ['ejercicio', 'practica', 'guia', 'tp', 'trabajo practico', 'problema']),
    ('resumenes',            ['resumen', 'sintesis', 'ficha']),
    ('apuntes',              ['apunte', 'teorico', 'clase', 'nota']),
    # fallback → 'otros'
]

CATEGORY_LABELS = {
    'parciales':            'Parcial',
    'finales':              'Final',
    'integradores':         'Integrador',
    'ejercicios-resueltos': 'Ejercicios',
    'resumenes':            'Resumen',
    'apuntes':              'Apuntes',
    'otros':                'Material',
}

# Pares (regex, reemplazo) para expandir ordinales en títulos
ORDINAL_SUBS = [
    (r'\b1er?\b',    'Primer'),
    (r'\b2do?\b',    'Segundo'),
    (r'\b3er?\b',    'Tercer'),
    (r'\bprimer\b',  'Primer'),
    (r'\bsegundo\b', 'Segundo'),
    (r'\btercer\b',  'Tercer'),
]

# Regex para extraer año del nombre del archivo (1990-2099)
YEAR_RE = re.compile(r'\b(19|20)\d{2}\b')

# Aliases: nombre corto/abreviado en el Drive → nombre canónico en la DB
# Las claves se comparan con fuzzy matching (≥ 0.75) después de normalizar.
ALIASES = {
    "análisis i":          "análisis matemático i",
    "análisis ii":         "análisis matemático ii",
    "filosofía":           "filosofía general",
    "física i":            "física mecánica",
    "física ii":           "física, electricidad y magnetismo",
    "química i":           "química general",
    "química ii":          "química aplicada",
    "marketing":           "marketing y emprendedurismo",
    "gestión sostenible":  "gestión sostenible y seguridad industrial",
    "mantenimiento":       "mantenimiento y confiabilidad industrial",
    "mecánica racional":   "mecánica racional y mecanismos",
    "proyecto final":      "proyecto final de carrera",
    "pps":                 "práctica profesional supervisada",
    "anaydis":             "análisis y diseño de algoritmos",
}


# ── Helpers de texto ───────────────────────────────────────────────────────────
def normalize(text):
    """Minúsculas, sin tildes, espacios colapsados."""
    nfkd = unicodedata.normalize('NFD', text.lower())
    plain = ''.join(c for c in nfkd if unicodedata.category(c) != 'Mn')
    return re.sub(r'[\s_\-]+', ' ', plain).strip()


def _strip_to_words(text):
    """Normalización agresiva: solo alfanuméricos y espacios (quita °, /, etc.)."""
    plain = normalize(text)
    plain = re.sub(r'[^a-z0-9 ]', ' ', plain)
    return re.sub(r' +', ' ', plain).strip()


def is_year_folder(name):
    """
    Devuelve el número de año (1-5) si el nombre corresponde a una carpeta de año
    académico, sin importar mayúsculas, tildes ni formato del ordinal.
    Ejemplos reconocidos: "1er Año", "Primer Año", "1° Año", "año 1", "Segundo Año".
    Devuelve None si no es una carpeta de año.
    """
    plain = _strip_to_words(name)
    if not _ANO_RE.search(plain):
        return None
    for year, pat in _YEAR_PATTERNS:
        if pat.search(plain):
            return year
    return None


def is_cuatrimestre_folder(name):
    """
    Devuelve el número de cuatrimestre (1 o 2) si el nombre es una capa intermedia
    de cuatrimestre, o None si no lo es.
    Reconoce: "Primer cuatrimestre", "2do cuatrimestre", "1° Cuatrimestre", etc.
    """
    plain = _strip_to_words(name)
    if not _CUATRI_RE.search(plain):
        return None
    for num, pat in _CUATRI_PATTERNS:
        if pat.search(plain):
            return num
    return 0  # "cuatrimestre" sin ordinal (ej: carpeta genérica)


def classify(filename, ancestors):
    """Devuelve el slug de categoría más adecuado para el archivo."""
    combined = normalize(' '.join([filename] + ancestors))
    for slug, keywords in CATEGORY_RULES:
        if any(kw in combined for kw in keywords):
            return slug
    return 'otros'


def clean_title(filename, ancestors, cat_slug, fallback_year=None):
    """
    Genera un título legible para el recurso.
    - El año (si existe) se mueve al final entre paréntesis: "Final Julio (2017)".
    - Si no hay año en el nombre se usa fallback_year (del modifiedTime del Drive).
    - fallback_year debe ser un string de 4 dígitos o None.
    """
    stem = Path(filename).stem

    # Eliminar tokens de hash/ID (6+ hex aislados que no sean años)
    stem = re.sub(r'(?<![a-zA-Z])[0-9a-f]{6,}(?![a-zA-Z0-9])', '', stem, flags=re.I)
    # Normalizar separadores
    stem = re.sub(r'[\s_\-\.]+', ' ', stem).strip()

    # Extraer año del nombre y quitarlo del stem
    year_match = YEAR_RE.search(stem)
    year = year_match.group() if year_match else fallback_year
    if year_match:
        stem = YEAR_RE.sub('', stem)
        stem = re.sub(r'\s+', ' ', stem).strip()

    # Palabras útiles: más de 2 caracteres (excluye artículos/preposiciones cortas)
    words  = stem.split()
    useful = [w for w in words if len(w) > 2]

    if len(useful) >= 2:
        body = ' '.join(w.capitalize() for w in useful)
        for pattern, replacement in ORDINAL_SUBS:
            body = re.sub(pattern, replacement, body, flags=re.I)
    elif len(useful) == 1:
        body = useful[0].capitalize()
        for pattern, replacement in ORDINAL_SUBS:
            body = re.sub(pattern, replacement, body, flags=re.I)
    else:
        # Sin info útil en el nombre → inferir desde carpeta padre + categoría
        label  = CATEGORY_LABELS.get(cat_slug, 'Material')
        parent = ancestors[-1] if ancestors else ''
        pf_norm = normalize(parent)
        for pattern, full in ORDINAL_SUBS:
            if re.search(pattern, pf_norm):
                cat_label = CATEGORY_LABELS.get(cat_slug, '').lower()
                label = f'{full} {cat_label}'.strip()
                break
        body = label

    title = f'{body} ({year})' if year else body
    return title[:200] or filename[:200]


# ── Helpers de Drive ───────────────────────────────────────────────────────────
def list_folder(service, folder_id):
    """Lista todos los items de una carpeta (maneja paginación)."""
    items, page_token = [], None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields='nextPageToken, files(id, name, mimeType, modifiedTime)',
            orderBy='folder,name',
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        items.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return items


def collect_files(service, folder_id, ancestors):
    """
    Recorre recursivamente toda la estructura dentro de una carpeta de materia
    y devuelve lista de (file_item, [carpetas_ancestro]).
    Los nombres de subcarpetas se acumulan en ancestors para ayudar a clasificar.
    """
    results = []
    for item in list_folder(service, folder_id):
        if item['mimeType'] == FOLDER_MIME:
            results.extend(
                collect_files(service, item['id'], ancestors + [item['name']])
            )
        elif Path(item['name']).suffix.lower() in ALLOWED_EXT:
            results.append((item, ancestors))
    return results


def get_subject_folders(service, parent_id, indent='  '):
    """
    Devuelve la lista de carpetas de materias bajo parent_id.
    Pasa transparentemente a través de capas intermedias de cuatrimestre
    (ej: "Primer cuatrimestre", "2do Cuatrimestre") sin tratarlas como materias.
    Funciona recursivamente por si hay más de un nivel de capas intermedias.
    """
    folders = []
    for item in list_folder(service, parent_id):
        if item['mimeType'] != FOLDER_MIME:
            continue
        cuatri = is_cuatrimestre_folder(item['name'])
        if cuatri is not None:
            label = f'C{cuatri}' if cuatri else 'cuatrimestre'
            print(f'{indent}[{label}] "{item["name"]}" — entrando...')
            folders.extend(get_subject_folders(service, item['id'], indent + '  '))
        else:
            folders.append(item)
    return folders


def download_file(service, file_id, dest):
    """Descarga un archivo del Drive usando MediaIoBaseDownload (OAuth service account)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    with open(dest, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


# ── Mapeo de materias ──────────────────────────────────────────────────────────
def resolve_alias(folder_name):
    """
    Compara folder_name contra las claves de ALIASES con fuzzy matching.
    Si alguna clave alcanza score ≥ 0.75, devuelve el nombre canónico (el valor).
    Devuelve None si ningún alias coincide lo suficiente.
    """
    norm = normalize(folder_name)
    best_canonical, best_score = None, 0.0
    for alias_key, canonical in ALIASES.items():
        score = difflib.SequenceMatcher(None, norm, normalize(alias_key)).ratio()
        if score > best_score:
            best_canonical, best_score = canonical, score
    return best_canonical if best_score >= 0.75 else None


def match_subject(folder_name, subjects, threshold=0.75):
    """
    Devuelve (Subject, score) para el mejor match.
    Devuelve (None, score) si el score está por debajo del umbral.
    """
    norm = normalize(folder_name)
    best, best_score = None, 0.0
    for s in subjects:
        score = difflib.SequenceMatcher(None, norm, normalize(s.name)).ratio()
        if score > best_score:
            best, best_score = s, score
    return (best, best_score) if best_score >= threshold else (None, best_score)


# ── Helpers de DB ──────────────────────────────────────────────────────────────
def get_category(subject_id, slug):
    return Category.query.filter_by(subject_id=subject_id, slug=slug).first()


def create_extra_category(subject_id, name):
    """Último recurso: crea una categoría de primer nivel para esta materia."""
    cat = Category(
        subject_id=subject_id,
        parent_id=None,
        name=name,
        slug=slugify(name) + '-extra',
        order=99,
    )
    db.session.add(cat)
    db.session.flush()
    print(f'        [NUEVA CAT] "{name}" creada (subject_id={subject_id})')
    return cat


# ── Log de progreso ────────────────────────────────────────────────────────────
def load_log():
    if Path(LOG_FILE).exists():
        with open(LOG_FILE, encoding='utf-8') as f:
            data = json.load(f)
        n = len(data.get('processed', {}))
        if n:
            print(f'Retomando desde log existente ({n} archivo(s) ya registrado(s)).')
        return data
    return {'processed': {}, 'unmapped_folders': []}


def save_log(log):
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Migra contenido del Drive a la plataforma.')
    parser.add_argument(
        '--test',
        action='store_true',
        help='Modo prueba: procesa solo la primera materia encontrada sin descargar ni guardar.',
    )
    parser.add_argument(
        '--retry-unmapped',
        action='store_true',
        help='Solo procesar las carpetas sin mapear registradas en migration_log.json.',
    )
    args = parser.parse_args()
    test_mode      = args.test
    retry_unmapped = args.retry_unmapped

    if not Path(CREDENTIALS_FILE).exists():
        sys.exit(f'✗ No se encontró {CREDENTIALS_FILE} en la raíz del proyecto.')

    app = create_app()
    with app.app_context():
        creds = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE, scopes=SCOPES
        )
        service = build('drive', 'v3', credentials=creds, cache_discovery=False)

        # Verificar acceso a la raíz
        try:
            root_meta = service.files().get(fileId=ROOT_ID, fields='name').execute()
            print(f'Drive raíz: {root_meta["name"]}')
        except HttpError as e:
            sys.exit(f'✗ No se pudo acceder a la carpeta raíz del Drive: {e}')

        if test_mode:
            print('╔══════════════════════════════════════════════════════════╗')
            print('║  MODO PRUEBA — no se descarga ni se guarda nada en la DB ║')
            print('╚══════════════════════════════════════════════════════════╝')

        log      = load_log()
        processed: dict = log['processed']
        unmapped: set   = set(log.get('unmapped_folders', []))

        all_subjects = Subject.query.all()
        admin = User.query.filter_by(is_admin=True).first()
        if not admin:
            sys.exit('✗ No hay usuario admin. Ejecutá init_db.py primero.')

        stats = {
            'success':        0,
            'skipped':        0,
            'error':          0,
            'categories':     {},
            'new_categories': 0,
        }

        # ── 1. Carpetas de año ─────────────────────────────────────────────────
        print('\nListando carpetas de año...')
        root_items   = list_folder(service, ROOT_ID)
        year_folders = [
            item for item in root_items
            if item['mimeType'] == FOLDER_MIME
            and is_year_folder(item['name']) is not None
        ]

        if not year_folders:
            sys.exit('✗ No se encontraron carpetas de año en la raíz del Drive.')

        ignored = [
            item['name'] for item in root_items
            if not (item['mimeType'] == FOLDER_MIME
                    and is_year_folder(item['name']) is not None)
        ]
        print(f'Carpetas de año: {", ".join(f["name"] for f in year_folders)}')
        if ignored:
            print(f'Ignorados en raíz: {", ".join(ignored)}')

        # ── 2. Recorrer año → materia → archivos ───────────────────────────────
        found_first_subject = False  # usado por --test para cortar tras la primera materia
        used_titles: dict   = {}     # (subject_id, category_id) → set[str] títulos ya usados

        for year_folder in sorted(year_folders, key=lambda x: is_year_folder(x['name']) or 0):
            if test_mode and found_first_subject:
                break
            print(f'\n── {year_folder["name"]} {"─" * 46}')

            subject_folders = get_subject_folders(service, year_folder['id'])

            for sf in subject_folders:
                if test_mode and found_first_subject:
                    break

                # --retry-unmapped: saltar carpetas que ya fueron mapeadas correctamente
                if retry_unmapped and sf['name'] not in unmapped:
                    continue

                # Resolver alias antes del matching normal
                canonical   = resolve_alias(sf['name'])
                search_name = canonical if canonical else sf['name']
                subject, score = match_subject(search_name, all_subjects)

                if subject is None:
                    if sf['name'] not in unmapped:
                        unmapped.add(sf['name'])
                        if not test_mode:
                            log['unmapped_folders'] = list(unmapped)
                            save_log(log)
                    alias_note = f', alias→"{canonical}"' if canonical else ''
                    print(f'  [SIN MAPEO] "{sf["name"]}" (score={score:.2f}{alias_note}) — omitida')
                    continue

                # Mapeada: si estaba en unmapped (resuelta ahora), sacarla del log
                was_unmapped = sf['name'] in unmapped
                if was_unmapped:
                    unmapped.discard(sf['name'])
                    if not test_mode:
                        log['unmapped_folders'] = list(unmapped)
                        save_log(log)

                found_first_subject = True
                print(f'\n  {sf["name"]}')
                if canonical:
                    print(f'  [alias] "{sf["name"]}" → "{canonical}"')
                if was_unmapped:
                    print(f'  [resuelto] estaba en sin-mapear')
                print(f'  → {subject.name}  (score={score:.2f})')

                files = collect_files(service, sf['id'], [])
                if not files:
                    print('    (sin archivos)')
                    continue
                print(f'    {len(files)} archivo(s)')

                for file_item, ancestors in files:
                    file_id = file_item['id']

                    if not test_mode and file_id in processed:
                        stats['skipped'] += 1
                        continue

                    try:
                        cat_slug = classify(file_item['name'], ancestors)
                        category = get_category(subject.id, cat_slug)

                        # Fallback 1: categoría 'otros'
                        if category is None:
                            category = get_category(subject.id, 'otros')

                        # Fallback 2 (último recurso): crear categoría nueva
                        if category is None and not test_mode:
                            label    = cat_slug.replace('-', ' ').title()
                            category = create_extra_category(subject.id, label)
                            cat_slug = category.slug
                            stats['new_categories'] += 1

                        cat_display  = category.slug if category else f'{cat_slug} [faltaría crear]'

                        # Año de respaldo desde modifiedTime si el nombre no tiene año
                        mt = file_item.get('modifiedTime', '')
                        fallback_year = mt[:4] if mt and mt[:4].isdigit() else None

                        base_title = clean_title(
                            file_item['name'], ancestors, cat_slug, fallback_year
                        )

                        # Deduplicación dentro de la misma materia + categoría
                        dedup_key = (subject.id, category.id if category else 0)
                        used      = used_titles.setdefault(dedup_key, set())
                        title     = base_title
                        counter   = 2
                        while title in used:
                            title = f'{base_title} {counter}'
                            counter += 1
                        used.add(title)

                        ext = Path(file_item['name']).suffix.lower()

                        display_name = file_item['name'][:42]
                        if test_mode:
                            print(f'    ~ {display_name:<42}  [{cat_display:<22}]  "{title}"')
                        else:
                            fname = uuid.uuid4().hex + ext
                            rel   = Path('uploads') / subject.slug / cat_display / fname
                            dest  = STATIC_DIR / rel

                            print(f'    ↓ {display_name:<42}  [{cat_display:<22}]  "{title}"')

                            download_file(service, file_id, dest)

                            resource = Resource(
                                title=title,
                                file_path=rel.as_posix(),
                                subject_id=subject.id,
                                category_id=category.id,
                                uploaded_by_id=admin.id,
                            )
                            db.session.add(resource)
                            db.session.commit()

                            processed[file_id] = {
                                'status':      'ok',
                                'drive_name':  file_item['name'],
                                'title':       title,
                                'subject':     subject.name,
                                'category':    cat_display,
                                'resource_id': resource.id,
                                'ts':          datetime.now().isoformat(),
                            }

                        stats['success'] += 1
                        stats['categories'][cat_slug] = (
                            stats['categories'].get(cat_slug, 0) + 1
                        )

                    except Exception as exc:
                        if not test_mode:
                            db.session.rollback()
                        print(f'    ✗ {file_item["name"][:50]}: {exc}')
                        if not test_mode:
                            processed[file_id] = {
                                'status':     'error',
                                'drive_name': file_item['name'],
                                'error':      str(exc),
                                'ts':         datetime.now().isoformat(),
                            }
                        stats['error'] += 1

                    finally:
                        if not test_mode:
                            log['processed']        = processed
                            log['unmapped_folders'] = list(unmapped)
                            save_log(log)

        # ── 3. Resumen ─────────────────────────────────────────────────────────
        print('\n' + '═' * 60)
        print('RESUMEN (SIMULACIÓN — nada fue guardado)' if test_mode else 'RESUMEN')
        print('═' * 60)
        print(f'  Archivos subidos:       {stats["success"]}')
        print(f'  Ya procesados (skip):   {stats["skipped"]}')
        print(f'  Errores:                {stats["error"]}')
        print(f'  Carpetas sin mapear:    {len(unmapped)}')
        if stats['new_categories']:
            print(f'  Categorías nuevas:      {stats["new_categories"]}')

        if stats['categories']:
            print('\n  Por categoría:')
            for cat, n in sorted(stats['categories'].items(), key=lambda x: -x[1]):
                print(f'    {cat:<28}  {n:>4}')

        if unmapped:
            print('\n  Carpetas sin mapear:')
            for name in sorted(unmapped):
                print(f'    - {name}')

        total = stats['success'] + stats['error']
        in_otros = stats['categories'].get('otros', 0)
        if total:
            pct_otros = in_otros / total * 100
            print(f'\n  En "Otros":  {in_otros}/{total}  ({pct_otros:.0f}%)')

        print()


if __name__ == '__main__':
    main()
