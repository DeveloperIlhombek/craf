#!/usr/bin/env bash
# GitHub Actions dan keladigan yagona buyruq (authorized_keys dagi command= orqali majburlangan).
# Kalit faqat shu skriptni ishga tushira oladi: zaxira + git pull + craf_* modullarni yangilash.
# Xato bo'lsa ham Odoo qayta yoqiladi (sayt to'xtab qolmasin).
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"
LOG="/opt/craf/backups/deploy-$(date +%Y%m%d-%H%M%S).log"
mkdir -p /opt/craf/backups
exec 9>/tmp/craf-deploy.lock
if ! flock -n 9; then
  echo "Boshqa yangilash ketyapti — kutilmoqda..."
  flock 9
fi
echo "== Craf avto-yangilash: $(date '+%F %T') ==" | tee "$LOG"
./update.sh 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
if [ "$RC" -ne 0 ]; then
  echo "XATO (kod $RC): Odoo qayta yoqilmoqda" | tee -a "$LOG"
  docker compose up -d 2>&1 | tee -a "$LOG"
fi
ls -1t /opt/craf/backups/deploy-*.log 2>/dev/null | tail -n +31 | xargs -r rm -f
echo "Log: $LOG"
exit "$RC"
