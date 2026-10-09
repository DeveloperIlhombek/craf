#!/usr/bin/env bash
# Craf bazasi + fayllar (filestore) zaxirasi: ../backups/craf-YYYYMMDD-HHMM.zip
# Eski nusxalar BACKUP_KEEP_DAYS kundan keyin o'chiriladi.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
set -a; . ./.env; set +a

STAMP=$(date +%Y%m%d-%H%M)
NAME="${DB_NAME}-${STAMP}.zip"
echo "$(date '+%F %T') zaxira: $NAME"

docker compose run --rm --no-deps -T --entrypoint sh odoo -c \
  'printf "[options]\\ndata_dir = /var/lib/odoo\\nlist_db = True\\n" > /tmp/db.conf && odoo db -c /tmp/db.conf --db_host "$HOST" --db_port "$PORT" -r "$USER" -w "$PASSWORD" dump "$1" "/backups/$2"' \
  sh "$DB_NAME" "$NAME"

ls -lh "../backups/$NAME"
find ../backups -maxdepth 1 -name "${DB_NAME}-*.zip" -mtime +"${BACKUP_KEEP_DAYS:-14}" -print -delete
