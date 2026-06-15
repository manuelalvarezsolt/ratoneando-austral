"""RAG: columna extracted_text + indice FTS5 sobre resources

Revision ID: b7f3a1c9d2e4
Revises: 6d544970e361
Create Date: 2026-06-15 00:00:00.000000

Agrega:
  - resources.extracted_text (texto extraido del PDF)
  - tabla virtual FTS5 'resources_fts' (external-content sobre 'resources')
    que indexa title, description y extracted_text
  - triggers que mantienen el indice sincronizado en INSERT/UPDATE/DELETE
  - backfill inicial del indice con las filas existentes

FTS5 external-content: el indice NO duplica el texto, lo lee de 'resources'
via content_rowid='id'. Por eso hacen falta los triggers para sincronizar.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7f3a1c9d2e4'
down_revision = '6d544970e361'
branch_labels = None
depends_on = None


def upgrade():
    # 1) Columna nueva. SQLite soporta ADD COLUMN sin batch.
    op.add_column('resources', sa.Column('extracted_text', sa.Text(), nullable=True))

    # 2) Tabla virtual FTS5 (external content). remove_diacritics 2 hace que
    #    "busqueda" matchee "búsqueda" (clave para español).
    op.execute("""
        CREATE VIRTUAL TABLE resources_fts USING fts5(
            title,
            description,
            extracted_text,
            content='resources',
            content_rowid='id',
            tokenize="unicode61 remove_diacritics 2"
        );
    """)

    # 3) Triggers de sincronizacion.
    op.execute("""
        CREATE TRIGGER resources_fts_ai AFTER INSERT ON resources BEGIN
            INSERT INTO resources_fts(rowid, title, description, extracted_text)
            VALUES (new.id, new.title, new.description, new.extracted_text);
        END;
    """)
    op.execute("""
        CREATE TRIGGER resources_fts_ad AFTER DELETE ON resources BEGIN
            INSERT INTO resources_fts(resources_fts, rowid, title, description, extracted_text)
            VALUES ('delete', old.id, old.title, old.description, old.extracted_text);
        END;
    """)
    op.execute("""
        CREATE TRIGGER resources_fts_au AFTER UPDATE ON resources BEGIN
            INSERT INTO resources_fts(resources_fts, rowid, title, description, extracted_text)
            VALUES ('delete', old.id, old.title, old.description, old.extracted_text);
            INSERT INTO resources_fts(rowid, title, description, extracted_text)
            VALUES (new.id, new.title, new.description, new.extracted_text);
        END;
    """)

    # 4) Backfill del indice con las filas ya existentes (title + description;
    #    extracted_text todavia es NULL hasta correr el script de extraccion).
    op.execute("""
        INSERT INTO resources_fts(rowid, title, description, extracted_text)
        SELECT id, title, description, extracted_text FROM resources;
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS resources_fts_au;")
    op.execute("DROP TRIGGER IF EXISTS resources_fts_ad;")
    op.execute("DROP TRIGGER IF EXISTS resources_fts_ai;")
    op.execute("DROP TABLE IF EXISTS resources_fts;")
    with op.batch_alter_table('resources') as batch_op:
        batch_op.drop_column('extracted_text')
