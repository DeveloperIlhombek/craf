#!/usr/bin/env bash
# Craf: serverni tekshirish — FAQAT O'QIYDI, hech narsani o'zgartirmaydi.
# .env / parol fayllari o'qilmaydi va chiqarilmaydi.
#   curl -fsSL https://raw.githubusercontent.com/DeveloperIlhombek/craf/master/deploy/check-server.sh | sudo bash
export LC_ALL=C
h() { printf '\n===== %s =====\n' "$*"; }
has() { command -v "$1" >/dev/null 2>&1; }
ver() { local name="$1"; shift; if has "$1"; then printf '%-16s %s\n' "$name" "$("$@" 2>&1 | head -1)"; else printf '%-16s -\n' "$name"; fi; }

h "Tizim"
[ -r /etc/os-release ] && . /etc/os-release && echo "OS:          $PRETTY_NAME"
echo "Yadro:       $(uname -r) ($(uname -m))"
echo "Hostname:    $(hostname)"
echo "Ishlayapti:  $(uptime -p 2>/dev/null)"
echo "Yuklama:     $(cut -d' ' -f1-3 /proc/loadavg)"
echo "CPU:         $(nproc) yadro —$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2)"
echo "Vaqt zonasi: $(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null)"

h "Xotira va swap"
free -h
swapon --show 2>/dev/null

h "Disk"
df -hT -x tmpfs -x devtmpfs -x overlay -x squashfs -x efivarfs 2>/dev/null

h "Tarmoq"
ip -4 -brief addr 2>/dev/null | grep -v '^lo'
echo "Tashqi IP: $(curl -fsS4 --max-time 5 https://ifconfig.me 2>/dev/null || echo '?')"

h "Tinglayotgan portlar (TCP)"
ss -tlnpH 2>/dev/null | awk '{p=$6; gsub(/users:\(\("/,"",p); gsub(/".*/,"",p); print $4, p}' | sort -t: -k2 -n | uniq

h "Firewall"
if has ufw; then ufw status 2>/dev/null | head -25; else echo "ufw yo'q"; fi

h "Dasturlar versiyasi"
ver docker docker --version
if has docker; then printf '%-16s %s\n' "docker compose" "$(docker compose version 2>&1 | head -1)"; fi
ver docker-compose docker-compose --version
ver nginx nginx -v
ver caddy caddy version
ver apache2 apache2 -v
ver certbot certbot --version
ver psql psql --version
ver mysql mysql --version
ver redis-server redis-server --version
ver node node -v
ver npm npm -v
ver pm2 pm2 -v
ver python3 python3 --version
ver git git --version

h "Docker konteynerlar"
if has docker; then
  timeout 20 docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>&1
  h "Docker compose loyihalar"
  timeout 20 docker compose ls -a 2>&1
  h "Docker tarmoqlar"
  timeout 20 docker network ls --format '{{.Name}}\t{{.Driver}}' 2>&1
  h "Docker volume lar"
  timeout 20 docker volume ls --format '{{.Name}}' 2>&1
  h "Docker disk"
  timeout 30 docker system df 2>&1
else
  echo "docker yo'q"
fi

h "Nginx saytlar"
if has nginx; then
  for f in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
    [ -e "$f" ] || continue
    echo "--- $f"
    grep -hE '^\s*(listen|server_name|proxy_pass|root|ssl_certificate)\s' "$f" 2>/dev/null | sed -E 's/^\s+//' | sort -u
  done
  nginx -t 2>&1 | tail -1
else
  echo "nginx yo'q"
fi

h "SSL sertifikatlar"
if has certbot; then
  certbot certificates 2>/dev/null | grep -E 'Certificate Name|Domains|Expiry Date'
fi
ls /etc/letsencrypt/live 2>/dev/null

h "Ishlayotgan xizmatlar (asosiylaridan tashqari)"
systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | awk '{print $1}' \
  | grep -vE '^(systemd-|dbus|getty|serial-getty|user@|polkit|rsyslog|cron|ssh|ModemManager|snapd|accounts-daemon|irqbalance|packagekit|qemu-guest|cloud-|atd|chrony|multipathd|udisks|unattended|networkd-dispatcher|containerd|docker|fwupd|upower|thermald|lvm2)'

if has pm2; then
  h "PM2 jarayonlar"
  pm2 jlist 2>/dev/null | python3 -c "import json,sys
try:
  for p in json.load(sys.stdin): print(p['name'], p['pm2_env'].get('status'), p['pm2_env'].get('pm_cwd',''))
except Exception as e: print('-')" 2>/dev/null
fi

h "PostgreSQL (tizimda, Docker dan tashqari)"
if systemctl list-unit-files 2>/dev/null | grep -q '^postgresql'; then
  echo "postgresql: $(systemctl is-active postgresql 2>/dev/null)"
  ls /etc/postgresql 2>/dev/null
else
  echo "tizim PostgreSQL yo'q"
fi

h "Cron (root)"
crontab -l 2>/dev/null | grep -vE '^\s*(#|$)'
ls /etc/cron.d 2>/dev/null

h "Papkalar hajmi"
du -sh /root/* /opt/* /srv/* /var/www/* /home/* 2>/dev/null | sort -h | tail -30

h "Craf uchun"
for p in 8069 8072 18069 18072; do
  if ss -tlnH "( sport = :$p )" 2>/dev/null | grep -q .; then echo "port $p: BAND"; else echo "port $p: bo'sh"; fi
done
[ -e /opt/craf ] && echo "/opt/craf: bor" || echo "/opt/craf: yo'q"
echo
echo "Tekshiruv tugadi."
