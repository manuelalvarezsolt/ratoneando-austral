# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# Activate virtual environment (Windows)
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Initialize database and seed data (creates admin user + careers)
python init_db.py

# Run development server (localhost:5000, debug mode)
python run.py
```

No test suite or linter is configured. Manual testing is done through the Flask dev server.

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
- `init_db.py` is fully idempotent and safe to run against an existing database: uses `db.create_all()` (never drops tables), skips existing users/careers/subjects, and never touches uploaded resources, comments, or contributions.
- The fixed category tree is enforced by the event listener; do not create categories manually outside of that structure without updating the listener.
- Max upload size: 50 MB. Allowed extensions: pdf, doc, docx, ppt, pptx, txt, png, jpg, jpeg (admin upload UI restricts to PDF).
- Admin credentials seeded by `init_db.py`: `admin@austral.edu.ar` / `admin123`.
