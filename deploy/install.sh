#!/usr/bin/env bash
# Craf — VPS ga o'rnatish (Ubuntu 22.04 / 24.04 yoki Debian 12).
#
#   curl -fsSL https://raw.githubusercontent.com/DeveloperIlhombek/craf/master/deploy/install.sh | sudo bash -s -- craf.example.uz
#
# Rejim avtomatik tanlanadi:
#   * serverda nginx 80-portda ishlayapti (boshqa saytlar bor) -> Odoo 127.0.0.1 da, nginx ga
#     yangi sayt (faqat craf.conf) qo'shiladi, SSL certbot bilan. Boshqa saytlarga tegilmaydi.
#   * bo'sh server -> Caddy 80/443 ni oladi, HTTPS avtomatik (domensiz bo'lsa IP orqali HTTP).
# Qayta ishga tushirish xavfsiz: mavjud .env, parollar va nginx sozlamasi o'zgarmaydi.
set -euo pipefail

REPO_URL="${CRAF_REPO:-https://github.com/DeveloperIlhombek/craf.git}"
BRANCH="${CRAF_BRANCH:-master}"
APP_DIR="${CRAF_DIR:-/opt/craf}"
DOMAIN="${1:-}"

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33mDIQQAT: %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mXATO: %s\033[0m\n' "$*" >&2; exit 1; }
port_busy() { ss -tlnH "( sport = :$1 )" 2>/dev/null | grep -q .; }

[ "$(id -u)" -eq 0 ] || die "root sifatida ishga tushiring (sudo)."

# ---------------------------------------------------------------- rejim
if ss -tlnpH '( sport = :80 )' 2>/dev/null | grep -q '"nginx"'; then
  MODE=nginx
  [ -n "$DOMAIN" ] || die "Serverda nginx ishlayapti — Craf uchun domen kerak:
   curl -fsSL https://raw.githubusercontent.com/DeveloperIlhombek/craf/master/deploy/install.sh | sudo bash -s -- craf.example.uz"
  command -v certbot >/dev/null 2>&1 || warn "certbot topilmadi — SSL ni keyin qo'lda olasiz."
elif port_busy 80 || port_busy 443; then
  die "80/443-port band (nginx emas). Qaysi dastur ishlatayotganini tekshiring: ss -tlnp"
else
  MODE=caddy
fi
say "Rejim: $MODE${DOMAIN:+, domen: $DOMAIN}"

# ---------------------------------------------------------------- paketlar (faqat yo'qlari)
need=()
for c in curl git openssl; do command -v "$c" >/dev/null 2>&1 || need+=("$c"); done
command -v crontab >/dev/null 2>&1 || need+=(cron)
if [ "${#need[@]}" -gt 0 ]; then
  say "O'rnatilmoqda: ${need[*]}"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq "${need[@]}" >/dev/null
fi

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

# ---------------------------------------------------------------- kod
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

# ---------------------------------------------------------------- .env
if [ ! -f .env ]; then
  ODOO_PORT=8069;    while port_busy "$ODOO_PORT"; do ODOO_PORT=$((ODOO_PORT + 1)); done
  ODOO_WS_PORT=8072; while port_busy "$ODOO_WS_PORT" || [ "$ODOO_WS_PORT" = "$ODOO_PORT" ]; do ODOO_WS_PORT=$((ODOO_WS_PORT + 1)); done
  say ".env yaratilmoqda (tasodifiy parollar; Odoo portlari 127.0.0.1:$ODOO_PORT / $ODOO_WS_PORT)"
  ( umask 077; cat > .env <<EOF
DB_USER=odoo
DB_PASSWORD=$(openssl rand -hex 24)
DB_NAME=craf
ADMIN_PASSWD=$(openssl rand -hex 16)
DOMAIN=$DOMAIN
SITE_ADDRESS=${DOMAIN:-:80}
COMPOSE_PROFILES=$([ "$MODE" = caddy ] && echo caddy)
ODOO_PORT=$ODOO_PORT
ODOO_WS_PORT=$ODOO_WS_PORT
BACKUP_KEEP_DAYS=14
EOF
  )
elif [ -n "$DOMAIN" ]; then
  for kv in "DOMAIN=$DOMAIN" "SITE_ADDRESS=$DOMAIN"; do
    k=${kv%%=*}
    if grep -q "^$k=" .env; then sed -i "s|^$k=.*|$kv|" .env; else echo "$kv" >> .env; fi
  done
fi
chmod 600 .env
set -a; . ./.env; set +a
ODOO_PORT=${ODOO_PORT:-8069}; ODOO_WS_PORT=${ODOO_WS_PORT:-8072}

# ---------------------------------------------------------------- odoo.conf
if [ ! -f config/odoo.conf ]; then
  if [ -n "${CRAF_WORKERS:-}" ]; then
    WORKERS=$CRAF_WORKERS
  elif [ "$MODE" = nginx ]; then
    WORKERS=2   # boshqa loyihalar bilan umumiy server — tejamkor
  else
    WORKERS=$(( $(nproc) * 2 + 1 )); BY_MEM=$(( MEM_MB / 600 ))
    [ "$BY_MEM" -lt 2 ] && BY_MEM=2
    [ "$WORKERS" -gt "$BY_MEM" ] && WORKERS=$BY_MEM
  fi
  say "config/odoo.conf (workers = $WORKERS)"
  sed -e "s|__ADMIN_PASSWD__|$ADMIN_PASSWD|" -e "s|__DB_NAME__|$DB_NAME|" -e "s|__WORKERS__|$WORKERS|" \
      odoo.conf.template > config/odoo.conf
fi

# ---------------------------------------------------------------- konteynerlar
say "Docker obrazlari (birinchi marta bir necha daqiqa)"
docker compose pull -q
# </dev/null: "curl | bash" bilan ishga tushirilganda konteyner skriptning qolgan qismini stdin dan o'qib olmasin
ODOO_ID=$(docker compose run --rm --no-deps -T --entrypoint sh odoo -c 'echo "$(id -u):$(id -g)"' </dev/null | tr -d '\r' | tail -n1)
chown "$ODOO_ID" config/odoo.conf ../backups
chmod 640 config/odoo.conf

say "Ishga tushirish"
docker compose up -d
printf 'Odoo kutilmoqda'
for _ in $(seq 1 60); do
  if curl -fsS --max-time 3 "http://127.0.0.1:$ODOO_PORT/web/health" >/dev/null 2>&1; then printf ' tayyor\n'; break; fi
  printf '.'; sleep 3
done

cat > /etc/cron.d/craf-backup <<EOF
# Craf: har kuni 02:30 da (server vaqti) zaxira nusxa (baza + fayllar) -> $APP_DIR/backups
30 2 * * * root $APP_DIR/deploy/backup.sh >> /var/log/craf-backup.log 2>&1
EOF
chmod 644 /etc/cron.d/craf-backup

# ---------------------------------------------------------------- tashqariga chiqish
PUBLIC_IP=$(curl -fsS4 --max-time 5 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
URL="http://$PUBLIC_IP"

if [ "$MODE" = nginx ]; then
  NGX_AV=/etc/nginx/sites-available/craf.conf
  NGX_EN=/etc/nginx/sites-enabled/craf.conf
  if [ ! -f "$NGX_AV" ]; then
    say "nginx: yangi sayt $DOMAIN (faqat craf.conf)"
    sed -e "s|__DOMAIN__|$DOMAIN|g" -e "s|__ODOO_PORT__|$ODOO_PORT|g" -e "s|__ODOO_WS_PORT__|$ODOO_WS_PORT|g" \
        nginx-craf.conf.template > "$NGX_AV"
    ln -sf "$NGX_AV" "$NGX_EN"
    if ! nginx -t >/tmp/craf-nginx-test.log 2>&1; then
      rm -f "$NGX_EN" "$NGX_AV"
      cat /tmp/craf-nginx-test.log
      die "nginx sozlamasida xato — craf.conf olib tashlandi, boshqa saytlar o'zgarmadi."
    fi
    systemctl reload nginx
  fi
  URL="http://$DOMAIN"

  if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    URL="https://$DOMAIN"
  elif command -v certbot >/dev/null 2>&1; then
    RESOLVED=$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ')
    if ! echo " $RESOLVED " | grep -q " $PUBLIC_IP "; then
      warn "DNS: $DOMAIN -> ${RESOLVED:-topilmadi}, server IP: $PUBLIC_IP.
DNS da A yozuv qo'shing ($DOMAIN -> $PUBLIC_IP), 5-30 daqiqa kuting va skriptni qayta ishga tushiring — SSL o'shanda olinadi."
    else
      say "SSL sertifikat (certbot)"
      EXTRA=()
      [ -d /etc/letsencrypt/accounts ] || EXTRA+=(--register-unsafely-without-email)
      if certbot --nginx -d "$DOMAIN" --redirect --non-interactive --agree-tos "${EXTRA[@]}"; then
        URL="https://$DOMAIN"
      else
        warn "SSL olinmadi — sayt hozircha http orqali ishlaydi. Keyin: sudo certbot --nginx -d $DOMAIN --redirect"
      fi
    fi
  fi
else
  [ "$SITE_ADDRESS" != ":80" ] && URL="https://$SITE_ADDRESS"
  if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
  fi
fi

# ---------------------------------------------------------------- yakun
DB_EXISTS=$(docker compose exec -T db psql -U "$DB_USER" -d postgres -Atc "select 1 from pg_database where datname='$DB_NAME'" </dev/null | tr -d '\r')
say "Tayyor: $URL"
if [ "$DB_EXISTS" != "1" ]; then
  cat <<EOF

"$DB_NAME" bazasi hali yo'q. Ikki yo'l:
  1) Kompyuterdagi bazani ko'chirish (tavsiya):
       Windows: Desktop\\Craf\\Craf-zaxira-olish.bat  ->  zaxira\\craf-....zip
       scp craf-....zip root@$PUBLIC_IP:$APP_DIR/backups/
       sudo $APP_DIR/deploy/restore.sh $APP_DIR/backups/craf-....zip
  2) Yangi bo'sh baza:
       sudo $APP_DIR/deploy/init-db.sh
EOF
fi
cat <<EOF

Parollar:  $APP_DIR/deploy/.env  (ADMIN_PASSWD — Odoo master paroli)
Yangilash: sudo $APP_DIR/deploy/update.sh
Zaxira:    har kuni 02:30 (server vaqti), $APP_DIR/backups ($BACKUP_KEEP_DAYS kun saqlanadi)
EOF
