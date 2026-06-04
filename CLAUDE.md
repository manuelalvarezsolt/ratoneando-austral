# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# Activate virtual environment (Windows)
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Apply DB migrations (crea/actualiza el esquema). Alembic gestiona el esquema.
flask --app run db upgrade

# Initialize/seed data (admin user + plan de estudios). Idempotente.
# Corre `db upgrade` internamente, así que en una base nueva alcanza con esto.
python init_db.py

# Run development server (localhost:5000, debug mode)
python run.py
```

No test suite or linter is configured. Manual testing is done through the Flask dev server.

### Migraciones (Flask-Migrate / Alembic)

El esquema lo gestionan las migraciones en `migrations/`, **no** `db.create_all()`.

```powershell
flask --app run db migrate -m "descripcion del cambio"   # autogenera tras cambiar models.py
flask --app run db upgrade                                 # aplica
flask --app run db downgrade                               # revierte una
```

**Transición en una base PREEXISTENTE** (que tenía tablas antes de adoptar Alembic):
ejecutar UNA sola vez `flask --app run db stamp head` para marcar el esquema actual
como base; recién después `db upgrade` aplica migraciones nuevas. `init_db.py` detecta
este caso y avisa.

## Architecture

Flask app using the application factory pattern (`app/__init__.py`). Three blueprints:

- **`auth_bp`** — `/auth/*` — login, register, logout. Registration restricted to `@austral.edu.ar` email domain.
- **`main_bp`** — `/*` — public content: career index, subject view, resource view, comments. All routes require login.
- **`admin_bp`** — `/admin/*` — subject CRUD with career placement, resource upload, category management. Requires `is_admin`.

## Database Models (`app/models.py`)

Seven SQLAlchemy models over SQLite (`ratoneando.db`):

- **Career** → **CareerSubject** ← **Subject**: Subjects are shared across careers; `CareerSubject` stores year and cuatrimestre placement. Biomédica is annual (no cuatrimestre).
- **Subject** → **Category**: Each subject gets a fixed two-level category tree auto-created by an SQLAlchemy event listener on insert: Exámenes (Parciales, Finales, Integradores), Ejercicios Resueltos, Resúmenes, Apuntes, Otros.
- **Category** → **Resource**: Resources belong to a category (and indirectly a subject). Files saved to `app/static/uploads/<subject_slug>/<category_slug>/` with UUID filenames.
- **Resource** → **Comment** ← **User**: Comments are attached to resources.

## Key Conventions

- Slugs are generated via `app/utils.slugify()`, which handles Spanish characters (á→a, ñ→n, ü→u, etc.).
- `init_db.py` is fully idempotent and safe to run against an existing database: applies pending Alembic migrations (`flask db upgrade`, never drops tables), skips existing users/careers/subjects, and never touches uploaded resources, comments, or contributions.
- The fixed category tree is enforced by the event listener; do not create categories manually outside of that structure without updating the listener.
- Max upload size: 50 MB. Allowed extensions: pdf, doc, docx, ppt, pptx, txt, png, jpg, jpeg (admin upload UI restricts to PDF).
- Admin credentials seeded by `init_db.py`: `admin@austral.edu.ar` / `admin123`.
