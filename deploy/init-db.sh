#!/usr/bin/env bash
# Yangi bo'sh craf bazasi: Odoo + barcha Craf modullari (craf_kalkulyator ularning hammasini tortadi).
# Ma'lumotlar bazasi menejeri yopiq (list_db = False), shuning uchun bu yerda vaqtinchalik sozlama ishlatiladi.
# Administrator: login "admin", parol — ADMIN_LOGIN_PASSWORD (.env ga yoziladi, kirgach o'zgartiring).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
set -a; . ./.env; set +a

EXISTS=$(docker compose exec -T db psql -U "$DB_USER" -d postgres -Atc "select 1 from pg_database where datname='$DB_NAME'" | tr -d '\r')
[ "$EXISTS" = "1" ] && { echo "\"$DB_NAME\" bazasi allaqachon bor." >&2; exit 1; }

if ! grep -q '^ADMIN_LOGIN_PASSWORD=' .env; then
  echo "ADMIN_LOGIN_PASSWORD=$(openssl rand -hex 8)" >> .env
fi
set -a; . ./.env; set +a

docker compose stop odoo
docker compose run --rm --no-deps -T --entrypoint sh odoo -c \
  'printf "[options]\\ndata_dir = /var/lib/odoo\\nlist_db = True\\n" > /tmp/db.conf && odoo db -c /tmp/db.conf --db_host "$HOST" --db_port "$PORT" -r "$USER" -w "$PASSWORD" init "$1" --language uz_UZ --country UZ --username admin --password "$2" \
   && odoo -c /etc/odoo/odoo.conf --db_host "$HOST" --db_port "$PORT" --db_user "$USER" --db_password "$PASSWORD" -d "$1" -i "$3" --stop-after-init --no-http' \
  sh "$DB_NAME" "$ADMIN_LOGIN_PASSWORD" "craf_kalkulyator,hr_attendance"
docker compose up -d
echo "Tayyor. Login: admin, parol: .env dagi ADMIN_LOGIN_PASSWORD"
