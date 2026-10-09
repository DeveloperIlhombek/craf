# Craf — alyuminiy profil zavodi uchun Odoo 19

Craf zavodini avtomatlashtirish: profil katalogi, ombor, ishlab chiqarish bosqichlari
(Pech → Press → Kimyoviy ishlov → Bo'yash va qadoqlash → Tayyor mahsulot ombori),
korzinkalar, QR pachka yorliqlari, kunlik hisobot va 1C uchun kalkulyator.

Odoo 19 Community + o'z modullarimiz (`addons/`).

## Modullar

| Modul | Vazifasi |
|---|---|
| `craf_profile` | Profil katalogi: kesim (kg/m), rang, uzunlik, dona/pachka, og'irlik, qoldiq pachkada |
| `craf_nomenklatura` | Mahsulot va xom-ashyo nomenklaturasi (1C nomlari bilan) |
| `craf_zavod` | Zavod xaritasi: sexlar, omborlar, qoldiqlar, oqimlar |
| `craf_kochirish` | Xaritadan ichki ko'chirish |
| `craf_label` | Pachkalar, QR yorliq (100×75 mm), skaner bilan ko'chirish |
| `craf_production` | Ishlab chiqarish hujjatlari asosi (smena, uskuna, mas'ul, MRP buyurtma) |
| `craf_foundry` | Pech: shixta, stalba (quyma), шлак, угар |
| `craf_extrusion` | Press: stalba sarfi, profil chiqishi, питак va brak |
| `craf_paint` | Bo'yash: rang, kukun, maydon, brak |
| `craf_mrp` | Manufacturing: bosqich turlari, ish markazlari, me'yorlar, BoM generatori, sarf hisoboti |
| `craf_dashboard` | Panel: kunlik ko'rsatkichlar |
| `craf_korzinka` | Korzinkalar (≤120 dona), kimyoviy ishlov, omborga topshirish |
| `craf_hisobot` | Kunlik hisobot (1C uchun): bo'limlar sarfi va chiqishi, xom-ashyo harakati, Excel, "1C ga kiritildi" |
| `craf_kalkulyator` | Hisobot ichidagi kalkulyator: pachka/qop → jami dona va kg; bo'yash/pech hujjatiga yozish |

`craf_kalkulyator` o'rnatilsa, qolgan barcha Craf modullari bog'liqlik orqali o'rnatiladi.

## Kompyuterda (Windows, Docker Desktop)

`Desktop\Craf` papkasi: `docker-compose.yml`, `config\odoo.conf`, `addons\`.
Modullar `addons\` ichida. Python kodi o'zgarsa — `Odoo-qayta-ishga-tushirish.bat`,
so'ng Odoo → Ilovalar → modul → Yangilash.

## VPS ga o'rnatish

**Talablar:** Ubuntu 22.04 / 24.04 (yoki Debian 12), kamida 2 vCPU, 4 GB RAM (2 GB ham ishlaydi — swap qo'shiladi),
20+ GB disk. Domen bo'lsa — uning A yozuvi server IP siga qaratilgan bo'lishi kerak (HTTPS avtomatik).

### 1. O'rnatish

Serverga SSH orqali kiring va bitta buyruq:

```bash
curl -fsSL https://raw.githubusercontent.com/DeveloperIlhombek/craf/master/deploy/install.sh | sudo bash -s -- craf.example.uz
```

Domen bo'lmasa, oxiridagi `craf.example.uz` ni yozmang — sayt `http://SERVER_IP` da ochiladi.

Skript: Docker o'rnatadi, kodni `/opt/craf` ga oladi, tasodifiy parollar bilan `deploy/.env` va
`deploy/config/odoo.conf` yaratadi, PostgreSQL 17 + Odoo 19 + Caddy (HTTPS) ni ishga tushiradi
va har kungi zaxirani (02:30) yoqadi.

### 2. Bazani kompyuterdan ko'chirish

1. Kompyuterda: `windows\Craf-zaxira-olish.bat` ni `Desktop\Craf` ga qo'yib ishga tushiring →
   `Desktop\Craf\zaxira\craf-YYYYMMDD-HHMM.zip` (baza + fayllar).
2. Serverga yuboring:
   ```powershell
   scp zaxira\craf-20261009-1400.zip root@SERVER_IP:/opt/craf/backups/
   ```
3. Serverda tiklang:
   ```bash
   sudo /opt/craf/deploy/restore.sh /opt/craf/backups/craf-20261009-1400.zip
   ```

Login va parollar kompyuterdagi bilan bir xil bo'ladi.

Ko'chirish o'rniga yangi bo'sh baza kerak bo'lsa: `sudo /opt/craf/deploy/init-db.sh`.

### 3. Yangilash

Kodni GitHub ga yuborgandan keyin serverda:

```bash
sudo /opt/craf/deploy/update.sh
```

Avval zaxira oladi, keyin `git pull`, barcha `craf_*` modullarni yangilaydi va Odoo ni qayta ishga tushiradi.

### Zaxira

- Har kuni 02:30 da: `/opt/craf/backups/craf-YYYYMMDD-HHMM.zip`, 14 kun saqlanadi (`BACKUP_KEEP_DAYS`).
- Qo'lda: `sudo /opt/craf/deploy/backup.sh`.
- Zaxiralarni vaqti-vaqti bilan boshqa joyga (kompyuterga) ham ko'chirib turing:
  `scp root@SERVER_IP:/opt/craf/backups/craf-*.zip .`

### Xavfsizlik

- `deploy/.env` va `deploy/config/odoo.conf` git ga kirmaydi (parollar shu yerda, faqat serverda).
- Ma'lumotlar bazasi menejeri yopiq (`list_db = False`), faqat `craf` bazasi ochiladi.
- PostgreSQL tashqariga ochilmagan; tashqarida faqat 80/443 portlar (Caddy).
- Odoo administrator parolini kuchli qiling; ixtiyoriy — Odoo da ikki bosqichli kirish (2FA).

### Foydali buyruqlar

```bash
cd /opt/craf/deploy
sudo docker compose ps                 # holat
sudo docker compose logs -f odoo       # Odoo jurnali
sudo docker compose restart odoo       # qayta ishga tushirish
```

## Tuzilma

```
addons/      Craf modullari (Odoo 19)
deploy/      VPS: docker-compose, Caddy, o'rnatish/yangilash/zaxira/tiklash skriptlari
windows/     Kompyuterdagi Odoo dan zaxira olish (.bat)
```
