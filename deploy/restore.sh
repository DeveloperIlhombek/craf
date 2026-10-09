#!/usr/bin/env bash
# Odoo zaxirasini (zip: baza + fayllar) craf bazasiga tiklash.
#   sudo /opt/craf/deploy/restore.sh /opt/craf/backups/craf-20261009-1400.zip
# Mavjud baza bo'lsa, avval uning zaxirasi olinadi, keyin almashtiriladi.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
set -a; . ./.env; set +a

ZIP="${1:-}"
[ -n "$ZIP" ] && [ -f "$ZIP" ] || { echo "Ishlatish: $0 <zaxira.zip> [-y]" >&2; exit 1; }
ZIP=$(readlink -f "$ZIP")
BACKUPS=$(readlink -f ../backups)
if [ "$(dirname "$ZIP")" != "$BACKUPS" ]; then
  cp "$ZIP" "$BACKUPS/"
  ZIP="$BACKUPS/$(basename "$ZIP")"
fi
chmod 644 "$ZIP"

EXISTS=$(docker compose exec -T db psql -U "$DB_USER" -d postgres -Atc "select 1 from pg_database where datname='$DB_NAME'" | tr -d '\r')
if [ "$EXISTS" = "1" ]; then
  if [ "${2:-}" != "-y" ]; then
    read -r -p "\"$DB_NAME\" bazasi $(basename "$ZIP") bilan almashtiriladi (oldin zaxira olinadi). Davom etasizmi? [ha/yo'q] " ANSWER
    [ "$ANSWER" = "ha" ] || { echo "To'xtatildi."; exit 1; }
  fi
  ./backup.sh
fi

echo "Tiklanmoqda: $(basename "$ZIP") -> $DB_NAME"
docker compose stop odoo
docker compose run --rm --no-deps -T --entrypoint sh odoo -c \
  'printf "[options]\\ndata_dir = /var/lib/odoo\\nlist_db = True\\n" > /tmp/db.conf && odoo db -c /tmp/db.conf --db_host "$HOST" --db_port "$PORT" -r "$USER" -w "$PASSWORD" load --move -f "$1" "/backups/$2"' \
  sh "$DB_NAME" "$(basename "$ZIP")"
docker compose up -d odoo
echo "Tayyor. Odoo 10-20 soniyada ochiladi."
