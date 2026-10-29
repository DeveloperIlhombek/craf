# Avtomatik serverga chiqarish (GitHub Actions)

`master` ga merge bo'lganda (addons/ yoki deploy/ o'zgarsa) GitHub serverga SSH bilan ulanadi va
`deploy/gh-deploy.sh` ishlaydi: zaxira → `git pull` → craf_* modullarni yangilash. Xato bo'lsa Odoo qayta yoqiladi.
Log: serverda `/opt/craf/backups/deploy-*.log`, GitHub da Actions → «Serverga chiqarish».

Kalit faqat shu bitta skriptni ishga tushira oladi (`command=`), boshqa buyruq yoki shell ochib bo'lmaydi.

## Bir martalik sozlash (serverda, root)

```bash
cd /opt/craf && git pull --ff-only origin master
ssh-keygen -t ed25519 -N "" -C github-craf-deploy -f /root/.ssh/craf_deploy
echo "command=\"/opt/craf/deploy/gh-deploy.sh\",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty $(cat /root/.ssh/craf_deploy.pub)" >> /root/.ssh/authorized_keys
cat /root/.ssh/craf_deploy          # → DEPLOY_SSH_KEY (BEGIN...END qatorlari bilan)
ssh-keyscan -t ed25519 13.140.177.217   # → DEPLOY_KNOWN_HOSTS
```

GitHub: repo → Settings → Secrets and variables → Actions → New repository secret:
- `DEPLOY_HOST` = `13.140.177.217`
- `DEPLOY_SSH_KEY` = `craf_deploy` fayli matni
- `DEPLOY_KNOWN_HOSTS` = `ssh-keyscan` natijasi

So'ng serverdagi maxfiy nusxani o'chiring: `rm /root/.ssh/craf_deploy` (ochiq qismi `.pub` qolishi mumkin).

Sinov: Actions → «Serverga chiqarish» → Run workflow.

## O'chirish
`/root/.ssh/authorized_keys` dan `github-craf-deploy` qatorini o'chiring va GitHub secretlarini olib tashlang.
