"""
Sistema RAG liviano sobre los PDFs del repositorio.

Tres responsabilidades:
  1. Extracción de texto de PDFs con pdfplumber (tolerante a fallos).
  2. Búsqueda full-text con SQLite FTS5 (tabla 'resources_fts').
  3. Agente: arma contexto con los recursos relevantes y consulta Gemini.

No importa modelos a nivel módulo para evitar ciclos con app.services.
"""
import os
import re
import logging

import requests
from flask import current_app
from sqlalchemy import text

from app import db

logger = logging.getLogger(__name__)

# pdfminer (debajo de pdfplumber) es muy verboso con PDFs rotos; lo callamos.
logging.getLogger('pdfminer').setLevel(logging.ERROR)
logging.getLogger('pdfplumber').setLevel(logging.ERROR)

# Límites de extracción: evitan que un PDF enorme consuma memoria/tiempo
# y que el índice se infle. Suficiente para que el agente tenga contexto.
MAX_PAGES = 60
MAX_CHARS = 200_000

# Cuánto texto de cada recurso se mete en el prompt del agente.
CONTEXT_CHARS_PER_DOC = 1_500

GEMINI_URL = (
    'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
)


# --------------------------------------------------------------------------- #
# 1. Extracción de PDFs
# --------------------------------------------------------------------------- #
def resource_abs_path(resource):
    """Ruta absoluta en disco del archivo de un recurso, o None.

    Reutiliza la misma convención que app.utils.delete_uploaded_file:
    <root_path>/static/<file_path>. En producción static/uploads apunta
    (symlink) al volumen montado, así que esto resuelve igual.
    """
    if not resource.file_path:
        return None
    return os.path.join(current_app.root_path, 'static', resource.file_path)


def extract_text_from_pdf(path, max_pages=MAX_PAGES, max_chars=MAX_CHARS):
    """Extrae texto de un PDF. Devuelve string (posiblemente vacío si es
    escaneado o no tiene capa de texto). Lanza si el archivo está corrupto
    o no se puede abrir: el caller decide qué hacer."""
    import pdfplumber  # import perezoso: el server web no lo necesita siempre

    parts = []
    total = 0
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            if i >= max_pages:
                break
            try:
                chunk = page.extract_text() or ''
            except Exception:
                # Una página rota no debe tirar todo el PDF.
                continue
            if chunk:
                parts.append(chunk)
                total += len(chunk)
                if total >= max_chars:
                    break
    return '\n'.join(parts).strip()[:max_chars]


def index_resource(resource):
    """Extrae el texto de un recurso y lo guarda en resource.extracted_text.
    NO hace commit (lo hace el caller). Nunca lanza: ante cualquier problema
    deja '' (procesado, sin texto) para que el recurso quede indexado igual.

    Devuelve True si extrajo texto real, False si quedó vacío.
    """
    path = resource_abs_path(resource)
    if not path or not path.lower().endswith('.pdf') or not os.path.exists(path):
        resource.extracted_text = ''
        return False
    try:
        text_content = extract_text_from_pdf(path)
    except Exception:
        logger.warning('Falló la extracción de %s (resource %s)',
                       path, resource.id, exc_info=True)
        resource.extracted_text = ''
        return False
    resource.extracted_text = text_content
    return bool(text_content)


# --------------------------------------------------------------------------- #
# 2. Búsqueda FTS5
# --------------------------------------------------------------------------- #
# Stopwords muy comunes en español: solo aportan ruido al ranking.
_STOPWORDS = {
    'que', 'de', 'la', 'el', 'en', 'los', 'las', 'un', 'una', 'unos', 'unas',
    'del', 'al', 'y', 'o', 'es', 'son', 'se', 'su', 'sus', 'por', 'para',
    'con', 'sin', 'como', 'mas', 'pero', 'lo', 'le', 'me', 'mi', 'te', 'tu',
    'qué', 'cómo', 'cuál', 'cuáles', 'dónde', 'cuándo', 'porqué', 'sobre',
}


def _fts_query(q):
    """Convierte texto libre del usuario en una expresión MATCH segura.

    Tokeniza, descarta tokens cortos y stopwords, escapa comillas y une con OR
    (prioriza recall; el ranking bm25 ordena por relevancia). Si tras quitar
    stopwords no queda nada, las conserva (mejor algo que nada). Devuelve None
    si no hay tokens útiles -> el caller devuelve vacío sin tocar la DB.
    """
    tokens = [t for t in re.findall(r'\w+', q.lower(), flags=re.UNICODE)
              if len(t) >= 2]
    if not tokens:
        return None
    content = [t for t in tokens if t not in _STOPWORDS]
    tokens = content or tokens
    # Comillas dobles -> literal en FTS5; duplicarlas las escapa.
    return ' OR '.join('"{}"'.format(t.replace('"', '""')) for t in tokens)


def search_resources(query, limit=10):
    """Busca recursos relevantes con FTS5. Devuelve lista de dicts ordenada
    por relevancia (mejor primero). Cada item:
        {id, title, description, subject, category, snippet, score}
    """
    match = _fts_query(query)
    if not match:
        return []

    sql = text("""
        SELECT
            r.id            AS id,
            r.title         AS title,
            r.description   AS description,
            s.name          AS subject,
            c.name          AS category,
            snippet(resources_fts, 2, '[', ']', ' … ', 16) AS snippet,
            bm25(resources_fts) AS score
        FROM resources_fts
        JOIN resources  r ON r.id = resources_fts.rowid
        JOIN subjects   s ON s.id = r.subject_id
        JOIN categories c ON c.id = r.category_id
        WHERE resources_fts MATCH :match
        ORDER BY score
        LIMIT :limit
    """)
    rows = db.session.execute(sql, {'match': match, 'limit': limit}).mappings().all()
    return [dict(row) for row in rows]


# --------------------------------------------------------------------------- #
# 3. Agente (Gemini Flash Lite)
# --------------------------------------------------------------------------- #
def _get_extracted_text(resource_id):
    """Texto extraído de un recurso (para el contexto del prompt)."""
    row = db.session.execute(
        text("SELECT extracted_text FROM resources WHERE id = :id"),
        {'id': resource_id},
    ).scalar()
    return row or ''


def _build_context(results):
    """Arma el bloque de contexto a partir de los recursos recuperados."""
    blocks = []
    for r in results:
        body = _get_extracted_text(r['id'])[:CONTEXT_CHARS_PER_DOC].strip()
        if not body:
            # Sin texto extraído (escaneado): al menos damos título/descripción.
            body = (r.get('description') or '').strip()
        blocks.append(
            "[Recurso #{id}] {title}\n"
            "Materia: {subject} · Categoría: {category}\n"
            "Contenido: {body}".format(
                id=r['id'], title=r['title'],
                subject=r['subject'], category=r['category'],
                body=body or '(sin texto disponible)',
            )
        )
    return '\n\n---\n\n'.join(blocks)


def call_gemini(prompt, timeout=30):
    """Llama a Gemini generateContent (REST). Devuelve el texto de la
    respuesta. Lanza RuntimeError si no hay API key o si la API falla."""
    api_key = current_app.config.get('GEMINI_API_KEY')
    if not api_key:
        raise RuntimeError('GEMINI_API_KEY no configurada en el entorno.')

    model = current_app.config.get('GEMINI_MODEL', 'gemini-2.5-flash-lite')
    url = GEMINI_URL.format(model=model)
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.2,
            'maxOutputTokens': 1024,
        },
    }
    resp = requests.post(
        url,
        params={'key': api_key},
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except (KeyError, IndexError):
        # Puede venir bloqueado por safety o sin candidatos.
        logger.warning('Respuesta inesperada de Gemini: %s', data)
        raise RuntimeError('Gemini no devolvió una respuesta utilizable.')


PROMPT_TEMPLATE = """\
Sos el asistente de Ratoneando, un repositorio de material de estudio de la \
Universidad Austral. Respondé la pregunta del alumno usando ÚNICAMENTE el \
material listado abajo. Si el material no alcanza para responder, decilo con \
honestidad y sugerí qué recursos podrían servir. Respondé en español rioplatense, \
de forma concreta, y citá los recursos relevantes por su título.

=== MATERIAL DISPONIBLE ===
{context}
=== FIN DEL MATERIAL ===

Pregunta del alumno: {question}

Respuesta:"""


def answer_question(question, top_k=None):
    """Pipeline RAG completo: busca con FTS5, arma contexto y consulta Gemini.

    Devuelve dict:
        {answer, sources: [{id, title, subject, category}], used_ai: bool}
    Nunca lanza por culpa de Gemini: ante un fallo de la API devuelve una
    respuesta degradada con las fuentes encontradas.
    """
    top_k = top_k or current_app.config.get('RAG_TOP_K', 5)
    results = search_resources(question, limit=top_k)

    sources = [
        {'id': r['id'], 'title': r['title'],
         'subject': r['subject'], 'category': r['category']}
        for r in results
    ]

    if not results:
        return {
            'answer': ('No encontré material relacionado con tu pregunta en el '
                       'repositorio. Probá reformularla o con otras palabras clave.'),
            'sources': [],
            'used_ai': False,
        }

    prompt = PROMPT_TEMPLATE.format(
        context=_build_context(results), question=question.strip(),
    )

    try:
        answer = call_gemini(prompt)
        used_ai = True
    except Exception as exc:
        logger.warning('Agente: fallback sin IA (%s)', exc)
        titles = ', '.join('“{}”'.format(s['title']) for s in sources)
        answer = ('No pude generar una respuesta con IA en este momento, pero '
                  'encontré material que puede servirte: {}.'.format(titles))
        used_ai = False

    return {'answer': answer, 'sources': sources, 'used_ai': used_ai}
