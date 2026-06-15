"""API JSON del agente IA y la búsqueda full-text (FTS5).

Ambos endpoints requieren login (convención de la app + el agente consume
cuota de Gemini). /api/agente además está rate-limited.
"""
from functools import wraps

from flask import request, jsonify, url_for
from flask_login import current_user

from app import limiter
from app.api import api_bp
from app.rag import search_resources, answer_question


def api_login_required(f):
    """Como login_required pero devuelve 401 JSON en vez de redirigir al login
    (lo correcto para un cliente que espera JSON)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify(ok=False, error='Necesitás iniciar sesión.'), 401
        return f(*args, **kwargs)
    return wrapper


def _serialize(result):
    """Agrega la URL pública de detalle a un resultado de búsqueda."""
    return {
        'id': result['id'],
        'title': result['title'],
        'subject': result['subject'],
        'category': result['category'],
        'snippet': result.get('snippet') or '',
        'url': url_for('main.resource_view', resource_id=result['id']),
    }


@api_bp.route('/buscar')
@api_login_required
def buscar():
    """GET /api/buscar?q=...&n=10 — búsqueda FTS5, top N por relevancia."""
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify(ok=True, query=q, results=[])
    try:
        n = min(max(int(request.args.get('n', 10)), 1), 50)
    except (TypeError, ValueError):
        n = 10
    results = search_resources(q, limit=n)
    return jsonify(ok=True, query=q, results=[_serialize(r) for r in results])


@api_bp.route('/agente', methods=['POST', 'GET'])
@api_login_required
@limiter.limit('10 per minute; 100 per day')
def agente():
    """Pregunta al agente. Acepta:
        POST {"pregunta": "..."}  ó  GET ?q=...
    Devuelve {ok, pregunta, respuesta, fuentes, used_ai}.
    """
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        pregunta = (data.get('pregunta') or data.get('q')
                    or request.form.get('pregunta') or '')
    else:
        pregunta = request.args.get('q') or request.args.get('pregunta') or ''
    pregunta = pregunta.strip()

    if len(pregunta) < 3:
        return jsonify(ok=False, error='Escribí una pregunta más completa.'), 400

    result = answer_question(pregunta)
    fuentes = [
        {**s, 'url': url_for('main.resource_view', resource_id=s['id'])}
        for s in result['sources']
    ]
    return jsonify(
        ok=True,
        pregunta=pregunta,
        respuesta=result['answer'],
        fuentes=fuentes,
        used_ai=result['used_ai'],
    )
