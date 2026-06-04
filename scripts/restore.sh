#!/usr/bin/env bash
#
# Restaura un backup de Ratoneando Austral.
#
# Uso:  bash scripts/restore.sh /var/backups/ratoneando/20260604-030000
#
# Detiene la app antes de restaurar (si usás systemd, ajustá SERVICE).
#
set -euo pipefail

SRC="${1:?Pasá el directorio del backup a restaurar}"
APP_DIR="${APP_DIR:-/var/www/ratoneando-austral}"
UPLOADS_PARENT="$APP_DIR/app/static"

if [ -f "$APP_DIR/instance/ratoneando.db" ] || [ -d "$APP_DIR/instance" ]; then
  DB_DEST="$APP_DIR/instance/ratoneando.db"
else
  DB_DEST="$APP_DIR/ratoneando.db"
fi

echo "Restaurando desde: $SRC"
echo "→ DB destino:      $DB_DEST"
echo "→ Uploads destino: $UPLOADS_PARENT/uploads"
read -r -p "Esto SOBREESCRIBE los datos actuales. ¿Continuar? (escribí 'si'): " ok
[ "$ok" = "si" ] || { echo "Cancelado."; exit 1; }

# ── Base de datos ────────────────────────────────────────────────
if [ -f "$SRC/ratoneando.db.gz" ]; then
  mkdir -p "$(dirname "$DB_DEST")"
  gunzip -c "$SRC/ratoneando.db.gz" > "$DB_DEST"
  echo "DB restaurada."
else
  echo "ADVERTENCIA: no hay ratoneando.db.gz en $SRC."
fi

# ── Archivos subidos ─────────────────────────────────────────────
if [ -f "$SRC/uploads.tar.gz" ]; then
  rm -rf "$UPLOADS_PARENT/uploads"
  tar -xzf "$SRC/uploads.tar.gz" -C "$UPLOADS_PARENT"
  echo "Uploads restaurados."
else
  echo "ADVERTENCIA: no hay uploads.tar.gz en $SRC."
fi

echo "Listo. Reiniciá la app para tomar los datos restaurados."
