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
# O'rnatilgan craf_* modullar yangilanadi (-u), addons/ ga yangi qo'shilganlari o'rnatiladi (-i)
INSTALLED=$(docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -Atc \
  "select name from ir_module_module where name like 'craf\_%' and state = 'installed' order by name" | tr -d '\r' | paste -sd, -)
NEW=$(cd ../addons && for m in $(ls -d craf_*/ | tr -d '/'); do
        case ",$INSTALLED," in *",$m,"*) ;; *) echo "$m" ;; esac
      done | paste -sd, -)
ARGS=()
[ -n "$INSTALLED" ] && ARGS+=(-u "$INSTALLED")
[ -n "$NEW" ] && { ARGS+=(-i "$NEW"); echo "Yangi modullar o'rnatiladi: $NEW"; }
docker compose stop odoo
# Modullarni yangilash xato bilan to'xtasa ham Odoo qayta yoqilsin (sayt to'xtab qolmasin)
trap 'rc=$?; if [ $rc -ne 0 ]; then echo "XATO (kod $rc): yangilash bekor qilindi, Odoo qayta yoqilmoqda"; docker compose up -d; fi' EXIT
docker compose run --rm --no-deps -T --entrypoint sh odoo -c \
  'db="$1"; shift; exec odoo -c /etc/odoo/odoo.conf --db_host "$HOST" --db_port "$PORT" --db_user "$USER" --db_password "$PASSWORD" -d "$db" "$@" --stop-after-init --no-http' \
  sh "$DB_NAME" "${ARGS[@]}"
docker compose up -d
echo "Tayyor."
