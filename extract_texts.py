#!/usr/bin/env python
"""
Extracción masiva de texto de los PDFs existentes -> resources.extracted_text.

Alimenta el índice FTS5 / RAG. Pensado para correr una vez sobre los miles
de PDFs ya cargados, pero es seguro correrlo varias veces.

Características:
  - RESUMIBLE: sólo procesa filas con extracted_text IS NULL. Las que ya se
    procesaron (texto o '' por fallo/escaneado/saltado) se saltean. Si lo
    cortás con Ctrl-C, retomás corriéndolo de nuevo.
  - AISLAMIENTO POR PDF: cada extracción corre en un subproceso propio con
    timeout duro (--timeout) y tope de RAM (--mem-limit, Linux). Si un PDF
    cuelga o revienta la memoria, se mata ese subproceso, se marca el recurso
    con error y se sigue con el siguiente. Nunca tumba el backfill entero.
  - Commits por lote (--batch): si se interrumpe, no se pierde lo ya commiteado.
    Usá lotes chicos (p. ej. --batch 5) si querés guardar progreso muy seguido.
  - Logs a consola y a archivo (extract_texts.log), con progreso y resumen.

Uso:
    python extract_texts.py                       # procesa los pendientes
    python extract_texts.py --timeout 30          # máx 30s por PDF (default)
    python extract_texts.py --mem-limit 2048      # máx 2 GB de RAM por PDF
    python extract_texts.py --batch 5             # commits más frecuentes
    python extract_texts.py --limit 100           # sólo los primeros 100 (pruebas)
    python extract_texts.py --retry-empty         # reprocesa los que quedaron en ''
"""
import os
import sys
import time
import queue
import signal
import logging
import argparse
import multiprocessing

# IMPORTANTE: nada de imports de `app`/Flask a nivel módulo. Cada subproceso de
# extracción (multiprocessing 'spawn') re-importa este módulo; mantenerlo
# liviano evita cargar Flask/SQLAlchemy en cada worker. Los imports pesados
# viven dentro de main().

# Defaults de los límites por PDF.
DEFAULT_TIMEOUT = 30        # segundos
DEFAULT_MEM_LIMIT_MB = 2048  # MB (sólo Linux; en Windows se ignora)

logger = logging.getLogger('extract_texts')

# Flag de interrupción: Ctrl-C marca, terminamos el item actual y commiteamos.
_interrupted = False


def _handle_sigint(signum, frame):
    global _interrupted
    _interrupted = True
    logger.warning('Interrupción recibida: terminando el lote actual y guardando…')


# --------------------------------------------------------------------------- #
# Extracción aislada en subproceso (timeout + tope de RAM)
# --------------------------------------------------------------------------- #
def _extract_worker(path, max_pages, max_chars, mem_mb, q):
    """Corre en un subproceso. Extrae texto del PDF y lo devuelve por la cola.
    Replica la lógica de app.rag.extract_text_from_pdf a propósito: así el
    worker NO importa Flask/SQLAlchemy y arranca liviano dentro del tope de RAM.
    Pone en la cola una tupla (status, payload):
        ('ok', texto) | ('memory', '') | ('error', mensaje)
    """
    # Tope de memoria del proceso (Linux). En Windows no existe `resource`:
    # el timeout sigue protegiendo igual.
    if mem_mb:
        try:
            import resource as _res
            soft = int(mem_mb) * 1024 * 1024
            _res.setrlimit(_res.RLIMIT_AS, (soft, soft))
        except (ImportError, ValueError, OSError):
            pass

    try:
        import logging as _logging
        _logging.getLogger('pdfminer').setLevel(_logging.ERROR)
        import pdfplumber

        parts, total = [], 0
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= max_pages:
                    break
                try:
                    chunk = page.extract_text() or ''
                except Exception:
                    continue  # una página rota no tira todo el PDF
                if chunk:
                    parts.append(chunk)
                    total += len(chunk)
                    if total >= max_chars:
                        break
        text = '\n'.join(parts).strip()[:max_chars]
        q.put(('ok', text))
    except MemoryError:
        try:
            q.put(('memory', ''))
        except Exception:
            pass
    except Exception as exc:
        try:
            q.put(('error', repr(exc)[:200]))
        except Exception:
            pass


def extract_pdf_limited(path, timeout, mem_mb, max_pages, max_chars):
    """Extrae un PDF en un subproceso con timeout y tope de RAM.
    Devuelve (texto, status) con status en:
        'ok' | 'empty' | 'timeout' | 'memory' | 'error'
    Nunca lanza: ante cualquier problema devuelve ('', <motivo>).
    """
    ctx = multiprocessing.get_context('spawn')  # idéntico en Linux y Windows
    q = ctx.Queue()
    p = ctx.Process(target=_extract_worker,
                    args=(path, max_pages, max_chars, mem_mb, q))
    p.start()

    # Leemos ANTES de join: si el worker pone un texto grande, se quedaría
    # bloqueado escribiendo en el pipe hasta que alguien lea (y join colgaría).
    try:
        status, payload = q.get(timeout=timeout)
    except queue.Empty:
        if p.is_alive():
            # Sigue corriendo pasado el timeout -> colgado. Lo matamos.
            p.terminate()
            p.join()
            return '', 'timeout'
        # Terminó solo sin entregar resultado -> el SO lo mató o reventó.
        # En POSIX, exitcode negativo = matado por señal (típico del OOM killer
        # o de reventar el RLIMIT_AS); positivo = otro fallo fatal.
        p.join()
        if p.exitcode is not None and p.exitcode < 0:
            return '', 'memory'
        return '', 'error'

    p.join()
    if status == 'ok':
        return payload, ('ok' if payload else 'empty')
    return '', status  # 'memory' | 'error'


# --------------------------------------------------------------------------- #
# Programa principal
# --------------------------------------------------------------------------- #
def _setup_logging():
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%H:%M:%S')
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    fileh = logging.FileHandler('extract_texts.log', encoding='utf-8')
    fileh.setFormatter(fmt)
    logger.addHandler(console)
    logger.addHandler(fileh)


def main():
    parser = argparse.ArgumentParser(description='Extrae texto de PDFs a FTS5.')
    parser.add_argument('--batch', type=int, default=25,
                        help='Filas por commit (default 25). Bajalo (p. ej. 5) '
                             'para guardar progreso más seguido.')
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT,
                        help='Segundos máximos por PDF antes de saltearlo '
                             '(default %d).' % DEFAULT_TIMEOUT)
    parser.add_argument('--mem-limit', type=int, default=DEFAULT_MEM_LIMIT_MB,
                        help='Tope de RAM por PDF en MB (default %d, sólo Linux). '
                             '0 = sin límite.' % DEFAULT_MEM_LIMIT_MB)
    parser.add_argument('--limit', type=int, default=None,
                        help='Procesar como máximo N recursos (para pruebas).')
    parser.add_argument('--retry-empty', action='store_true',
                        help="Reprocesar también los que quedaron en '' (fallidos).")
    args = parser.parse_args()

    _setup_logging()
    signal.signal(signal.SIGINT, _handle_sigint)

    # Imports pesados acá adentro (ver nota arriba sobre 'spawn').
    from app import create_app, db
    from app.models import Resource
    from app.rag import resource_abs_path, MAX_PAGES, MAX_CHARS

    app = create_app()
    with app.app_context():
        # Filtramos por estado. NULL = pendiente; '' = procesado-sin-texto.
        q = Resource.query.filter(Resource.file_path.isnot(None))
        if args.retry_empty:
            q = q.filter((Resource.extracted_text.is_(None))
                         | (Resource.extracted_text == ''))
        else:
            q = q.filter(Resource.extracted_text.is_(None))

        # Tomamos sólo los IDs primero: el resultado no se invalida al ir
        # modificando/commiteando filas durante el loop.
        ids = [row.id for row in q.order_by(Resource.id).with_entities(Resource.id).all()]
        if args.limit:
            ids = ids[:args.limit]

        total = len(ids)
        if total == 0:
            logger.info('No hay recursos pendientes de extracción. Nada que hacer.')
            return

        mem_txt = ('%d MB' % args.mem_limit) if args.mem_limit else 'sin límite'
        logger.info('Procesando %d recursos (batch=%d, timeout=%.0fs, RAM=%s)…',
                    total, args.batch, args.timeout, mem_txt)
        started = time.time()
        ok = empty = errors = 0
        skipped = {'timeout': 0, 'memory': 0, 'error': 0}

        for i, rid in enumerate(ids, 1):
            if _interrupted:
                break
            resource = db.session.get(Resource, rid)
            if resource is None:
                continue

            path = resource_abs_path(resource)
            if not path or not path.lower().endswith('.pdf') or not os.path.exists(path):
                # Sin archivo local / no es PDF: queda indexado por título.
                resource.extracted_text = ''
                empty += 1
            else:
                text, status = extract_pdf_limited(
                    path, args.timeout, args.mem_limit, MAX_PAGES, MAX_CHARS)
                resource.extracted_text = text or ''
                if status == 'ok':
                    ok += 1
                elif status == 'empty':
                    empty += 1
                else:  # timeout | memory | error
                    errors += 1
                    skipped[status] = skipped.get(status, 0) + 1
                    logger.warning('  saltado [%s] recurso %s — %s',
                                   status, rid, os.path.basename(path))

            # Commit por lote (o al final).
            if i % args.batch == 0 or i == total:
                db.session.commit()
                elapsed = time.time() - started
                rate = i / elapsed if elapsed else 0
                eta = (total - i) / rate if rate else 0
                logger.info('  %d/%d (%.0f%%) | ok=%d vacíos=%d err=%d | %.2f/s | ETA %.0fs',
                            i, total, 100 * i / total, ok, empty, errors, rate, eta)

        # Si quedó algo sin commitear por la interrupción, lo guardamos.
        db.session.commit()

        done = ok + empty + errors
        logger.info('Listo. Procesados %d/%d | con texto=%d | sin texto=%d | '
                    'errores=%d (timeout=%d, RAM=%d, otros=%d)%s',
                    done, total, ok, empty, errors,
                    skipped['timeout'], skipped['memory'], skipped['error'],
                    ' (INTERRUMPIDO: corré de nuevo para continuar)' if _interrupted else '')


if __name__ == '__main__':
    main()
