#!/usr/bin/env bash
# Craf — VPS ga birinchi o'rnatish (Ubuntu 22.04 / 24.04 yoki Debian 12).
#
#   curl -fsSL https://raw.githubusercontent.com/DeveloperIlhombek/craf/master/deploy/install.sh | sudo bash -s -- craf.example.uz
#
# Domen bo'lmasa oxiridagi domenni yozmang — sayt server IP manzili orqali (HTTP) ochiladi.
# Qayta ishga tushirish xavfsiz: mavjud .env va parollar o'zgarmaydi.
set -euo pipefail

REPO_URL="${CRAF_REPO:-https://github.com/DeveloperIlhombek/craf.git}"
BRANCH="${CRAF_BRANCH:-master}"
APP_DIR="${CRAF_DIR:-/opt/craf}"
DOMAIN="${1:-}"

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mXATO: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "root sifatida ishga tushiring (sudo)."

say "Kerakli paketlar"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git openssl cron >/dev/null

if ! command -v docker >/dev/null 2>&1; then
  say "Docker o'rnatilmoqda"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || die "docker compose topilmadi"
systemctl enable --now docker >/dev/null 2>&1 || true

# Kichik serverlarda (RAM < 3 GB) swap bo'lmasa — 2 GB swap fayl
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$MEM_MB" -lt 3000 ] && [ "$(swapon --show --noheadings | wc -l)" -eq 0 ] && [ ! -f /swapfile ]; then
  say "Swap (2 GB) yaratilmoqda — RAM ${MEM_MB} MB"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

say "Kod: $REPO_URL ($BRANCH) -> $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" checkout --quiet "$BRANCH"
  git -C "$APP_DIR" pull --quiet --ff-only origin "$BRANCH"
else
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR/deploy"
mkdir -p config ../backups

if [ ! -f .env ]; then
  say ".env yaratilmoqda (tasodifiy parollar)"
  ( umask 077; cat > .env <<EOF
DB_USER=odoo
DB_PASSWORD=$(openssl rand -hex 24)
DB_NAME=craf
ADMIN_PASSWD=$(openssl rand -hex 16)
SITE_ADDRESS=${DOMAIN:-:80}
BACKUP_KEEP_DAYS=14
EOF
  )
elif [ -n "$DOMAIN" ]; then
  sed -i "s|^SITE_ADDRESS=.*|SITE_ADDRESS=$DOMAIN|" .env
fi
chmod 600 .env
set -a; . ./.env; set +a

if [ ! -f config/odoo.conf ]; then
  CPUS=$(nproc)
  WORKERS=$(( CPUS * 2 + 1 ))
  BY_MEM=$(( MEM_MB / 600 ))
  [ "$BY_MEM" -lt 2 ] && BY_MEM=2
  [ "$WORKERS" -gt "$BY_MEM" ] && WORKERS=$BY_MEM
  say "config/odoo.conf (workers = $WORKERS)"
  sed -e "s|__ADMIN_PASSWD__|$ADMIN_PASSWD|" -e "s|__DB_NAME__|$DB_NAME|" -e "s|__WORKERS__|$WORKERS|" \
      odoo.conf.template > config/odoo.conf
fi

say "Docker obrazlari"
docker compose pull -q
ODOO_ID=$(docker compose run --rm --no-deps -T --entrypoint sh odoo -c 'echo "$(id -u):$(id -g)"' | tr -d '\r' | tail -n1)
chown "$ODOO_ID" config/odoo.conf ../backups
chmod 640 config/odoo.conf

say "Ishga tushirish"
docker compose up -d

printf 'Odoo kutilmoqda'
for _ in $(seq 1 60); do
  if docker compose exec -T odoo python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8069/web/health', timeout=3)" >/dev/null 2>&1; then
    printf ' tayyor\n'; break
  fi
  printf '.'; sleep 3
done

cat > /etc/cron.d/craf-backup <<EOF
# Craf: har kuni 02:30 da zaxira nusxa (baza + fayllar) -> $APP_DIR/backups
30 2 * * * root $APP_DIR/deploy/backup.sh >> /var/log/craf-backup.log 2>&1
EOF
chmod 644 /etc/cron.d/craf-backup

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
fi

DB_EXISTS=$(docker compose exec -T db psql -U "$DB_USER" -d postgres -Atc "select 1 from pg_database where datname='$DB_NAME'" | tr -d '\r')
if [ "$SITE_ADDRESS" = ":80" ]; then
  URL="http://$(curl -fsS4 --max-time 5 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
else
  URL="https://$SITE_ADDRESS"
fi

say "Tayyor: $URL"
if [ "$DB_EXISTS" != "1" ]; then
  cat <<EOF

"$DB_NAME" bazasi hali yo'q. Ikki yo'l:
  1) Kompyuterdagi bazani ko'chirish (tavsiya):
       Windows: Desktop\\Craf\\Craf-zaxira-olish.bat  ->  zaxira\\craf-....zip
       scp craf-....zip root@SERVER:$APP_DIR/backups/
       sudo $APP_DIR/deploy/restore.sh $APP_DIR/backups/craf-....zip
  2) Yangi bo'sh baza:
       sudo $APP_DIR/deploy/init-db.sh
EOF
fi
cat <<EOF

Parollar: $APP_DIR/deploy/.env  (ADMIN_PASSWD — Odoo master paroli)
Yangilash: sudo $APP_DIR/deploy/update.sh
Zaxira:    har kuni 02:30, $APP_DIR/backups ($BACKUP_KEEP_DAYS kun saqlanadi)
EOF
