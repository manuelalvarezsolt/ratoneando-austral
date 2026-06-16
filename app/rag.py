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
from app.utils import slugify

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


# Palabras que mapean a una categoría de la DB. Si la query las menciona,
# restringimos la búsqueda a esos slugs (no son términos de contenido).
# "examen" abarca las tres hojas de Exámenes.
CATEGORY_KEYWORDS = {
    'parcial': {'parciales'}, 'parciales': {'parciales'},
    'final': {'finales'}, 'finales': {'finales'},
    'integrador': {'integradores'}, 'integradores': {'integradores'},
    'examen': {'parciales', 'finales', 'integradores'},
    'examenes': {'parciales', 'finales', 'integradores'},
    'resumen': {'resumenes'}, 'resumenes': {'resumenes'},
    'apunte': {'apuntes'}, 'apuntes': {'apuntes'},
    'guia': {'guias'}, 'guias': {'guias'},
}

# Tokens de 1 char que igual conservamos (numerales romanos: Análisis I vs II).
_KEEP_SHORT = {'i', 'v', 'x'}


def _query_tokens(query):
    """Tokens normalizados (minúscula, sin tildes) del texto del usuario.
    Reusa slugify para que 'Análisis I' y 'analisis i' den lo mismo."""
    return [t for t in slugify(query).split('-') if t]


def _fts_match(tokens):
    """Expresión MATCH de FTS5 a partir de tokens ya normalizados.
    Descarta stopwords y tokens de 1 char (salvo numerales romanos) y une con
    OR (prioriza recall; bm25 ordena). Devuelve None si no queda nada útil."""
    toks = [t for t in tokens
            if t not in _STOPWORDS and (len(t) >= 2 or t in _KEEP_SHORT)]
    toks = toks or [t for t in tokens if len(t) >= 2] or tokens
    if not toks:
        return None
    # Comillas dobles -> literal en FTS5; duplicarlas las escapa.
    return ' OR '.join('"{}"'.format(t.replace('"', '""')) for t in toks)


def _fts_search(match, cat_slugs, limit):
    """Búsqueda full-text sobre título/descripción/texto del recurso, con
    filtro opcional por categoría. Ordena por relevancia bm25."""
    params = {'match': match, 'limit': limit}
    cat_clause = ''
    if cat_slugs:
        keys = []
        for i, slug in enumerate(sorted(cat_slugs)):
            params['c%d' % i] = slug
            keys.append(':c%d' % i)
        cat_clause = ' AND c.slug IN (%s)' % ', '.join(keys)
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
        WHERE resources_fts MATCH :match""" + cat_clause + """
        ORDER BY score
        LIMIT :limit
    """)
    return [dict(row) for row in db.session.execute(sql, params).mappings().all()]


def _subject_search(content_tokens, cat_slugs, limit, exclude_ids):
    """Recall por MATERIA: recursos de las materias cuyo slug contiene TODOS los
    tokens de contenido (p. ej. 'analisis i' -> materia 'Análisis Matemático I').
    Cubre el caso en que el usuario nombra la materia pero el título del recurso
    no incluye ese término (el FTS solo indexa el texto del recurso, no la
    materia). Respeta el filtro de categoría y excluye los ya traídos."""
    subj_tokens = [t for t in content_tokens
                   if t not in _STOPWORDS and (len(t) >= 2 or t in _KEEP_SHORT)]
    if not subj_tokens or limit <= 0:
        return []

    from app.models import Subject, Category, Resource

    sq = Subject.query
    for t in subj_tokens:
        sq = sq.filter(Subject.slug.contains(t))
    subject_ids = [sid for (sid,) in sq.with_entities(Subject.id).limit(8).all()]
    if not subject_ids:
        return []

    rq = (db.session.query(Resource.id, Resource.title, Resource.description,
                           Subject.name, Category.name)
          .join(Subject, Subject.id == Resource.subject_id)
          .join(Category, Category.id == Resource.category_id)
          .filter(Resource.subject_id.in_(subject_ids)))
    if cat_slugs:
        rq = rq.filter(Category.slug.in_(cat_slugs))
    if exclude_ids:
        rq = rq.filter(~Resource.id.in_(exclude_ids))
    rq = rq.order_by(Resource.created_at.desc()).limit(limit)

    return [{'id': rid, 'title': title, 'description': desc,
             'subject': subj, 'category': cat, 'snippet': '', 'score': None}
            for (rid, title, desc, subj, cat) in rq.all()]


def search_resources(query, limit=10):
    """Busca recursos relevantes combinando FTS5 (texto del recurso) con
    matching por materia, más filtro por categoría según palabras clave.
    Devuelve lista de dicts: {id, title, description, subject, category,
    snippet, score}, los más relevantes primero.

    Ejemplos:
      - "parciales de análisis I" -> recursos de Análisis Matemático I,
        sólo de la categoría Parciales.
      - "algebra" -> material de las materias de Álgebra aunque el título del
        recurso sea genérico ("Parcial 2022").
    """
    tokens = _query_tokens(query)
    if not tokens:
        return []

    # 1) Categoría: separamos las palabras tipo parcial/final/resumen/apunte.
    cat_slugs = set()
    content_tokens = []
    for t in tokens:
        if t in CATEGORY_KEYWORDS:
            cat_slugs |= CATEGORY_KEYWORDS[t]
        else:
            content_tokens.append(t)

    # 2) Full-text sobre el texto del recurso (con filtro de categoría).
    match = _fts_match(content_tokens or tokens)
    results = _fts_search(match, cat_slugs, limit) if match else []

    # 3) Recall por materia para completar hasta `limit`.
    if len(results) < limit:
        seen = {r['id'] for r in results}
        results.extend(
            _subject_search(content_tokens, cat_slugs, limit - len(results), seen)
        )

    return results[:limit]


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


def call_gemini(contents, timeout=30):
    """Llama a Gemini generateContent (REST). `contents` puede ser un string
    (un único turno de usuario) o una lista de turnos al estilo Gemini
    [{'role': 'user'|'model', 'parts': [{'text': ...}]}, ...] para conversación
    multi-turn. Devuelve el texto de la respuesta. Lanza RuntimeError si no hay
    API key o si la API falla."""
    api_key = current_app.config.get('GEMINI_API_KEY')
    if not api_key:
        raise RuntimeError('GEMINI_API_KEY no configurada en el entorno.')

    if isinstance(contents, str):
        contents = [{'role': 'user', 'parts': [{'text': contents}]}]

    model = current_app.config.get('GEMINI_MODEL', 'gemini-2.5-flash-lite')
    url = GEMINI_URL.format(model=model)
    payload = {
        'contents': contents,
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
Universidad Austral. Tu única fuente de verdad es el MATERIAL listado abajo.

Reglas:
1. Para preguntas sobre contenido concreto (definiciones, qué entra en un \
parcial, fórmulas, fechas, datos puntuales): basate EXCLUSIVAMENTE en el \
MATERIAL y no inventes nada que no esté ahí. Si hay recursos relacionados, \
usalos aunque cubran el tema sólo en parte (podés aclarar qué quedó afuera); si \
NINGUNO tiene relación, respondé "No tengo ese material en el repositorio."
2. Para preguntas subjetivas o que piden criterio (p. ej. "cuál es el tema más \
importante", "qué conviene estudiar", "cómo me preparo"): combiná lo que haya en \
el MATERIAL con tu conocimiento general de la materia para dar una orientación \
útil y razonada. Dejá en claro qué es sugerencia general tuya y qué sale del \
material del repositorio.
3. Nunca inventes datos concretos del repositorio (fechas, cifras, ni qué \
contiene un recurso puntual) ni sugieras sitios web, libros, links ni fuentes \
externas al repositorio.
4. Adaptá el formato y el largo a la pregunta:
   - Si pide opinión o explicación: respondé en prosa, máximo 3 oraciones.
   - Si pide temas, contenidos o materiales: respondé con una lista concisa, un \
ítem por renglón, sin descripciones largas (el nombre del tema o del recurso a \
secas, a lo sumo una frase corta).
   - En cualquier otro caso, andá al grano: sin repetir ideas, sin relleno ni \
párrafos de más.

Estilo de la respuesta:
- Escribí en texto corrido y natural, como una persona que explica lo que sabe \
en voz alta, NO como un robot que formatea una respuesta.
- NADA de markdown: sin asteriscos (** o *), sin negritas ni títulos. Usá \
oraciones y párrafos normales, salvo cuando enumeres temas/contenidos/materiales: \
ahí va una lista concisa en texto plano (un ítem por renglón, sin asteriscos).
- No cites recursos con etiquetas ni corchetes en medio del texto (nada de \
"[Recurso #3]" ni "[...]"). Si necesitás mencionar un material, nombralo \
naturalmente por su título dentro de la oración.
- Español rioplatense natural, pero sin muletillas ni saludos al inicio: no \
empieces con "Che", "Mirá", "Bueno" ni similares. Arrancá directo por la respuesta.

=== MATERIAL DISPONIBLE ===
{context}
=== FIN DEL MATERIAL ===

Pregunta del alumno: {question}

Respuesta:"""


# Límites del historial de conversación que mandamos a Gemini (control de
# tokens/costo): cuántos mensajes previos y cuánto texto por mensaje.
HISTORY_MAX_TURNS = 10
HISTORY_MAX_CHARS = 4_000


def _history_to_contents(history):
    """Convierte un historial del front en turnos al estilo Gemini.
    Acepta items {'role': ..., 'content'/'text': ...}. Mapea cualquier rol de
    asistente a 'model' y el resto a 'user'. Ignora vacíos, recorta longitud y
    cantidad, y descarta turnos 'model' iniciales (Gemini espera que la
    conversación arranque con 'user')."""
    contents = []
    if not history:
        return contents
    for msg in list(history)[-HISTORY_MAX_TURNS:]:
        if not isinstance(msg, dict):
            continue
        text = (msg.get('content') or msg.get('text') or '').strip()
        if not text:
            continue
        role = str(msg.get('role') or '').lower()
        g_role = 'model' if role in ('assistant', 'model', 'bot', 'ia', 'ai') else 'user'
        contents.append({'role': g_role, 'parts': [{'text': text[:HISTORY_MAX_CHARS]}]})
    while contents and contents[0]['role'] == 'model':
        contents.pop(0)
    return contents


def answer_question(question, history=None, top_k=None):
    """Pipeline RAG completo: busca con FTS5, arma contexto y consulta Gemini.

    `history` (opcional) es el historial de la conversación previa
    [{'role': 'user'|'assistant', 'content': ...}, ...]; se manda a Gemini como
    turnos anteriores para que mantenga contexto. La pregunta actual va siempre
    como último turno, fundamentada en el MATERIAL recuperado para ESA pregunta.

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
    # Conversación = turnos previos + la pregunta actual fundamentada.
    contents = _history_to_contents(history)
    contents.append({'role': 'user', 'parts': [{'text': prompt}]})

    try:
        answer = call_gemini(contents)
        used_ai = True
    except Exception as exc:
        logger.warning('Agente: fallback sin IA (%s)', exc)
        titles = ', '.join('“{}”'.format(s['title']) for s in sources)
        answer = ('No pude generar una respuesta con IA en este momento, pero '
                  'encontré material que puede servirte: {}.'.format(titles))
        used_ai = False

    return {'answer': answer, 'sources': sources, 'used_ai': used_ai}
