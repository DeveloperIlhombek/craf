@echo off
chcp 65001 >nul
rem Craf: kompyuterdagi Odoo bazasidan zaxira (baza + fayllar) -> zaxira\craf-YYYYMMDD-HHMM.zip
rem Bu faylni Desktop\Craf papkasiga (docker-compose.yml yoniga) qo'ying va ikki marta bosing.
cd /d "%~dp0"
set "PATH=%ProgramFiles%\Docker\Docker\resources\bin;%PATH%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set "STAMP=%%i"
if not exist zaxira mkdir zaxira

echo Craf bazasidan zaxira olinmoqda (baza + fayllar)...
docker compose exec -T odoo sh -c "printf '[options]\ndata_dir = /var/lib/odoo\nlist_db = True\n' > /tmp/db.conf && odoo db -c /tmp/db.conf --db_host \"$HOST\" --db_port \"$PORT\" -r \"$USER\" -w \"$PASSWORD\" dump craf /tmp/craf-zaxira.zip"
if errorlevel 1 goto xato
docker compose cp odoo:/tmp/craf-zaxira.zip "zaxira\craf-%STAMP%.zip"
if errorlevel 1 goto xato
docker compose exec -T odoo rm -f /tmp/craf-zaxira.zip /tmp/db.conf

echo.
echo Tayyor: %CD%\zaxira\craf-%STAMP%.zip
echo.
echo VPS ga yuborish (PowerShell yoki CMD da):
echo   scp "zaxira\craf-%STAMP%.zip" root@SERVER_IP:/opt/craf/backups/
echo Keyin serverda:
echo   sudo /opt/craf/deploy/restore.sh /opt/craf/backups/craf-%STAMP%.zip
echo.
pause
exit /b 0

:xato
echo.
echo XATO: Docker Desktop va Odoo ishlayotganini tekshiring. Kerak bo'lsa faylni "Run as administrator" bilan oching.
pause
exit /b 1
