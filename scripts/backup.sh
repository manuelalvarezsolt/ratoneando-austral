#!/usr/bin/env bash
#
# Backup de Ratoneando Austral: base de datos SQLite + archivos subidos.
# Pensado para correr por cron en el servidor de producción (Linux).
#
# Uso manual:   bash scripts/backup.sh
# Cron diario:  0 3 * * * /var/www/ratoneando-austral/scripts/backup.sh >> /var/log/ratoneando-backup.log 2>&1
#
# Variables de entorno opcionales (con sus defaults):
#   APP_DIR         /var/www/ratoneando-austral
#   BACKUP_ROOT     /var/backups/ratoneando
#   RETENTION_DAYS  14
#
set -euo pipefail

APP_DIR="${APP_DIR:-/var/www/ratoneando-austral}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/ratoneando}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
UPLOADS_DIR="$APP_DIR/app/static/uploads"

# La DB es SQLite relativa → Flask la ubica en instance/. Detectamos ambas rutas.
if [ -f "$APP_DIR/instance/ratoneando.db" ]; then
  DB_PATH="$APP_DIR/instance/ratoneando.db"
elif [ -f "$APP_DIR/ratoneando.db" ]; then
  DB_PATH="$APP_DIR/ratoneando.db"
else
  DB_PATH=""
fi

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_ROOT/$TIMESTAMP"
mkdir -p "$DEST"

# ── Base de datos ────────────────────────────────────────────────
# Usamos el comando .backup de sqlite3: copia consistente incluso con
# la app escribiendo. NUNCA usar `cp` sobre una SQLite en uso (corrompe).
if [ -n "$DB_PATH" ]; then
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_PATH" ".backup '$DEST/ratoneando.db'"
    gzip "$DEST/ratoneando.db"
    echo "DB respaldada desde $DB_PATH"
  else
    echo "ADVERTENCIA: sqlite3 no está instalado (apt install sqlite3). Backup de DB omitido."
  fi
else
  echo "ADVERTENCIA: no se encontró la base de datos en $APP_DIR."
fi

# ── Archivos subidos ─────────────────────────────────────────────
if [ -d "$UPLOADS_DIR" ]; then
  tar -czf "$DEST/uploads.tar.gz" -C "$(dirname "$UPLOADS_DIR")" "$(basename "$UPLOADS_DIR")"
  echo "Uploads respaldados desde $UPLOADS_DIR"
fi

# ── Rotación: borrar backups más viejos que RETENTION_DAYS ───────
find "$BACKUP_ROOT" -maxdepth 1 -type d -name '20*' -mtime "+$RETENTION_DAYS" \
  -exec rm -rf {} + 2>/dev/null || true

echo "Backup OK: $DEST"
