#!/usr/bin/env python
"""
Extracción masiva de texto de los PDFs existentes -> resources.extracted_text.

Alimenta el índice FTS5 / RAG. Pensado para correr una vez sobre los miles
de PDFs ya cargados, pero es seguro correrlo varias veces.

Características:
  - RESUMIBLE: sólo procesa filas con extracted_text IS NULL. Las que ya se
    procesaron (texto o '' por fallo/escaneado) se saltean. Si lo cortás con
    Ctrl-C, retomás corriéndolo de nuevo.
  - Commits por lote (--batch, default 25): si se interrumpe, no se pierde el
    progreso ya commiteado.
  - Logs a consola y a archivo (extract_texts.log), con progreso y resumen.
  - Tolerante a PDFs corruptos / escaneados: nunca aborta por uno solo.

Uso:
    python extract_texts.py                # procesa los pendientes
    python extract_texts.py --batch 50
    python extract_texts.py --limit 100    # sólo los primeros 100 (pruebas)
    python extract_texts.py --retry-empty  # reprocesa los que quedaron en ''
"""
import sys
import time
import signal
import logging
import argparse

from app import create_app, db
from app.models import Resource
from app.rag import index_resource

# --------------------------------------------------------------------------- #
# Logging: consola + archivo
# --------------------------------------------------------------------------- #
logger = logging.getLogger('extract_texts')
logger.setLevel(logging.INFO)
_fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%H:%M:%S')
_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(_fmt)
_file = logging.FileHandler('extract_texts.log', encoding='utf-8')
_file.setFormatter(_fmt)
logger.addHandler(_console)
logger.addHandler(_file)

# Flag de interrupción: Ctrl-C marca, terminamos el item actual y commiteamos.
_interrupted = False


def _handle_sigint(signum, frame):
    global _interrupted
    _interrupted = True
    logger.warning('Interrupción recibida: terminando el lote actual y guardando…')


def main():
    parser = argparse.ArgumentParser(description='Extrae texto de PDFs a FTS5.')
    parser.add_argument('--batch', type=int, default=25,
                        help='Filas por commit (default 25).')
    parser.add_argument('--limit', type=int, default=None,
                        help='Procesar como máximo N recursos (para pruebas).')
    parser.add_argument('--retry-empty', action='store_true',
                        help="Reprocesar también los que quedaron en '' (fallidos).")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_sigint)

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

        logger.info('Procesando %d recursos (batch=%d)…', total, args.batch)
        started = time.time()
        ok = empty = errors = 0

        for i, rid in enumerate(ids, 1):
            if _interrupted:
                break
            resource = db.session.get(Resource, rid)
            if resource is None:
                continue
            try:
                got_text = index_resource(resource)  # set extracted_text, no commit
                if got_text:
                    ok += 1
                else:
                    empty += 1
            except Exception:
                # index_resource ya es tolerante, pero por las dudas.
                errors += 1
                resource.extracted_text = ''
                logger.exception('Error inesperado en recurso %s', rid)

            # Commit por lote (o al final).
            if i % args.batch == 0 or i == total:
                db.session.commit()
                elapsed = time.time() - started
                rate = i / elapsed if elapsed else 0
                eta = (total - i) / rate if rate else 0
                logger.info('  %d/%d (%.0f%%) | ok=%d vacíos=%d err=%d | %.1f/s | ETA %.0fs',
                            i, total, 100 * i / total, ok, empty, errors, rate, eta)

        # Si quedó algo sin commitear por la interrupción, lo guardamos.
        db.session.commit()

        done = ok + empty + errors
        logger.info('Listo. Procesados %d/%d | con texto=%d | sin texto=%d | errores=%d%s',
                    done, total, ok, empty, errors,
                    ' (INTERRUMPIDO: corré de nuevo para continuar)' if _interrupted else '')


if __name__ == '__main__':
    main()
