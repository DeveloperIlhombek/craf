#!/usr/bin/env bash
# GitHub dagi yangi kodni olib, Craf modullarini yangilaydi.
#   sudo /opt/craf/deploy/update.sh            — zaxira + git pull + modullarni yangilash
#   sudo /opt/craf/deploy/update.sh --no-backup
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
set -a; . ./.env; set +a

[ "${1:-}" = "--no-backup" ] || ./backup.sh

BRANCH=$(git rev-parse --abbrev-ref HEAD)
OLD=$(git rev-parse HEAD)
git pull --ff-only origin "$BRANCH"
NEW=$(git rev-parse HEAD)
echo "Kod: ${OLD:0:7} -> ${NEW:0:7}"

docker compose pull -q
# Barcha craf_* modullar (o'rnatilmaganlari e'tiborsiz qoladi)
MODULES=$(cd ../addons && ls -d craf_*/ | tr -d '/' | paste -sd, -)
docker compose stop odoo
docker compose run --rm --no-deps -T --entrypoint sh odoo -c \
  'odoo -c /etc/odoo/odoo.conf --db_host "$HOST" --db_port "$PORT" --db_user "$USER" --db_password "$PASSWORD" -d "$1" -u "$2" --stop-after-init --no-http' \
  sh "$DB_NAME" "$MODULES"
docker compose up -d
echo "Tayyor."
