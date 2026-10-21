"""Bitta umumiy Telegram bot: xabar yuborish, /start va buyruqlar, kunlik hisobot, minimal qoldiq eslatmasi.

Bot Telegram serveridan yangi xabarlarni o'zi so'rab oladi (getUpdates, har daqiqa) — webhook va ochiq port kerak emas.
Token — sozlamada (ir.config_parameter), mas'ullar va Telegram ID — craf.bolim.contact da.
"""
import html
import logging
from datetime import datetime, timedelta

import pytz
import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_sex.models.craf_sex import STAGE

_logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot%s/%s"
TZ = "Asia/Tashkent"
P_TOKEN = "craf_telegram.token"
P_BOT = "craf_telegram.bot_username"
P_OFFSET = "craf_telegram.update_offset"
P_HOUR = "craf_telegram.daily_hour"
P_LAST_DAILY = "craf_telegram.last_daily"
MAX_LEN = 4000
BOLIM_ICON = {"litey": "🔥", "press": "⚙️", "boyash": "🎨"}
HELP = ("Buyruqlar:\n/qoldiq — Liteyka xom-ashyo holati\n/hisobot — kechagi hisobot\n/id — Telegram ID ingiz")


class TelegramError(Exception):
    pass


def esc(value):
    return html.escape(str(value or ""), quote=False)


def num(value, digits=1):
    value = float(value or 0.0)
    if abs(value - round(value)) < 1e-9:
        digits = 0
    text = "{:,.{d}f}".format(value, d=digits)
    return text.replace(",", " ").replace(".", ",")


class CrafTelegram(models.AbstractModel):
    _name = "craf.telegram"
    _description = "Craf Telegram bot"

    # ================================================================== API
    def _param(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def _set_param(self, key, value):
        self.env["ir.config_parameter"].sudo().set_param(key, value)

    def _token(self):
        return (self._param(P_TOKEN) or "").strip()

    def _api(self, method, payload=None, timeout=15):
        token = self._token()
        if not token:
            raise TelegramError("Telegram bot tokeni sozlamada yozilmagan.")
        try:
            resp = requests.post(API_URL % (token, method), json=payload or {}, timeout=timeout)
            data = resp.json()
        except (requests.RequestException, ValueError) as err:
            raise TelegramError("Telegram bilan aloqa yo'q: %s" % err) from err
        if not data.get("ok"):
            raise TelegramError(data.get("description") or "Telegram xatosi (%s)" % resp.status_code)
        return data.get("result")

    @api.model
    def send(self, chat_id, text, kind="info", contact=None):
        """HTML matnni yuboradi (uzunini bo'lib); jurnalga yozadi. Muvaffaqiyatli bo'lsa True."""
        chat_id = str(chat_id or "").strip()
        if not chat_id:
            return False
        parts, chunk = [], ""
        for line in (text or "").split("\n"):
            if len(chunk) + len(line) + 1 > MAX_LEN and chunk:
                parts.append(chunk)
                chunk = ""
            chunk += line + "\n"
        if chunk.strip():
            parts.append(chunk)
        error = False
        for part in parts:
            try:
                self._api("sendMessage", {"chat_id": chat_id, "text": part, "parse_mode": "HTML",
                                          "disable_web_page_preview": True})
            except TelegramError as err:
                error = str(err)
                break
        self.env["craf.telegram.log"].sudo().create({
            "chat_id": chat_id, "contact_id": contact.id if contact else False,
            "bolim_id": contact.bolim_id.id if contact else False, "kind": kind,
            "text": text, "state": "error" if error else "sent", "error": error or False,
        })
        if error:
            _logger.warning("Telegram %s ga yuborilmadi: %s", chat_id, error)
        return not error

    @api.model
    def _contacts(self, code=None, flag=None):
        domain = [("active", "=", True), ("telegram_id", "!=", False), ("bolim_id", "!=", False)]
        if code:
            domain.append(("bolim_id.code", "=", code))
        if flag:
            domain.append((flag, "=", True))
        return self.env["craf.bolim.contact"].sudo().search(domain)

    def _send_contacts(self, contacts, text, kind):
        sent = 0
        for chat_id, group in self._group_by_chat(contacts).items():
            sent += self.send(chat_id, text, kind=kind, contact=group[0])
        return sent

    @staticmethod
    def _group_by_chat(contacts):
        res = {}
        for c in contacts:
            res.setdefault(c.telegram_id.strip(), []).append(c)
        return res

    # ================================================================== vaqt
    def _now(self):
        return pytz.utc.localize(datetime.utcnow()).astimezone(pytz.timezone(TZ))

    def _yesterday(self):
        return self._now().date() - timedelta(days=1)

    # ================================================================== hisobotlar
    def _litey_text(self, day, with_title=True):
        H = self.env["craf.litey.hisobot"].sudo().with_context(tz=TZ)
        d = H.get_data(fields.Date.to_string(day), fields.Date.to_string(day))
        k = d["kpi"]
        lines = []
        if with_title:
            lines.append("%s <b>Liteyka</b> — %s" % (BOLIM_ICON["litey"], day.strftime("%d.%m.%Y")))
        if k["melts"]:
            lines.append("Plavka: %s ta · pechga metall %s kg · stalba %s kg · угар %s %%" % (
                k["melts"], num(k["metal"], 0), num(k["billet"], 0), num(k["loss_pct"], 2)))
        else:
            lines.append("Plavka yozilmagan.")
        if k["drafts"]:
            lines.append("Qoralama plavka: %s ta" % k["drafts"])
        # ombor harakatlari bo'yicha (plavka hujjati bo'lmasa ham — Excel / qo'lda yozilgan sarf va kirim)
        for title, key in (("Sarf", "spent"), ("Kirim", "kirim"), ("Chiqdi", "out")):
            items = []
            for r in d["movement"]:
                value = {"spent": r["sarf_plavka"] + r["sarf_boshqa"], "kirim": r["kirim"],
                         "out": r["chiqish_plavka"] + r["chiqish_boshqa"]}[key]
                if value > 1e-6:
                    items.append((value, r))
            if items:
                items.sort(key=lambda x: -x[0])
                lines.append("%s: %s" % (title, "; ".join("%s %s %s" % (esc(r["name"]), num(v), esc(r["uom"]))
                                                          for v, r in items)))
        lines.append("")
        lines.append(self._stock_text())
        return "\n".join(lines)

    def _stock_text(self):
        H = self.env["craf.litey.hisobot"].sudo().with_context(tz=TZ)
        _bolim, period, warn, rows = H._forecast_rows()
        out = [r for r in rows if r["status"] in ("out", "neg")]
        low = [r for r in rows if r["status"] == "low"]
        soon = sorted([r for r in rows if r["status"] == "soon"],
                      key=lambda r: r["days_to_min"] if r["days_to_min"] is not None else (r["days_left"] or 0))
        main = sorted([r for r in rows if r["status"] == "ok" and r["days_left"] is not None],
                      key=lambda r: r["days_left"])[:6]
        lines = ["<b>Xom-ashyo</b> (o'rtacha sarf — oxirgi %s kun):" % period]
        if out:
            lines.append("⛔ Tugagan: " + ", ".join(esc(r["name"]) for r in out))
        for r in low:
            lines.append("⚠️ %s — %s %s (minimal %s)" % (esc(r["name"]), num(r["qty"]), esc(r["uom"]), num(r["min_qty"], 0)))
        for r in soon:
            tail = ", minimalgacha ~%s kun" % num(r["days_to_min"]) if r["days_to_min"] is not None else ""
            lines.append("⏳ %s — %s %s, ~%s kunga%s" % (esc(r["name"]), num(r["qty"]), esc(r["uom"]),
                                                      num(r["days_left"]), tail))
        for r in main:
            lines.append("• %s — %s %s, ~%s kunga" % (esc(r["name"]), num(r["qty"]), esc(r["uom"]), num(r["days_left"])))
        if len(lines) == 1:
            lines.append("Kuzatiladigan sarf yo'q.")
        return "\n".join(lines)

    def _stage_text(self, stage, day):
        key, label, model, _loc = STAGE[stage]
        Model = self.env[model].sudo()
        done = Model.search([("date", "=", day), ("state", "=", "done")])
        drafts = Model.search_count([("state", "=", "draft"), ("date", "<=", day)])
        lines = ["<b>%s</b>" % esc(label)]
        if done:
            for k in getattr(self.env["craf.sex"].sudo(), "_kpi_%s" % key)(done):
                sub = " (%s)" % esc(k["sub"]) if k.get("sub") else ""
                lines.append("• %s: %s%s%s" % (esc(k["label"]), esc(k["value"]),
                                              " " + esc(k["unit"]) if k.get("unit") else "", sub))
        else:
            lines.append("Hujjat yozilmagan.")
        if drafts:
            lines.append("Qoralama: %s ta" % drafts)
        return "\n".join(lines)

    @api.model
    def report_text(self, code, day=None):
        day = day or self._yesterday()
        if code == "litey":
            return self._litey_text(day)
        title = {"press": "Press", "boyash": "Bo'yash va qadoqlash"}[code]
        stages = ["press"] if code == "press" else ["kimyo", "boyash"]
        body = "\n\n".join(self._stage_text(s, day) for s in stages)
        return "%s <b>%s</b> — %s\n%s" % (BOLIM_ICON[code], title, day.strftime("%d.%m.%Y"), body)

    @api.model
    def send_daily(self, codes=None, day=None):
        """Kunlik hisobot — «Kunlik hisobot» belgilangan mas'ullarga. Yuborilgan xabarlar soni."""
        sent = 0
        for code in codes or ["litey", "press", "boyash"]:
            contacts = self._contacts(code, "notify_daily")
            if not contacts:
                continue
            try:
                text = self.report_text(code, day)
            except Exception as err:  # noqa: BLE001 — bitta bo'lim xatosi boshqalarini to'xtatmasin
                _logger.exception("Telegram: %s hisobotini tayyorlab bo'lmadi", code)
                text = "%s %s hisobotini tayyorlab bo'lmadi: %s" % (BOLIM_ICON[code], code, esc(err))
            sent += self._send_contacts(contacts, text, "report")
        return sent

    # ================================================================== minimal qoldiq
    @api.model
    def _min_qty_alerts(self, rows):
        if not self._token():
            return
        contacts = self._contacts("litey", "notify_min_qty")
        Tmpl = self.env["product.template"].sudo()
        bad, restored = [], []
        for r in rows:
            if not r["min_qty"]:
                continue
            tmpl = Tmpl.browse(r["tmpl_id"])
            is_bad = r["status"] in ("low", "out", "neg")
            if is_bad and not tmpl.craf_tg_alert:
                bad.append((r, tmpl))
            elif not is_bad and tmpl.craf_tg_alert:
                restored.append((r, tmpl))
        if not contacts or not (bad or restored):
            return
        lines = []
        if bad:
            lines.append("⚠️ <b>Liteyka: xom-ashyo minimal qoldiqdan kam</b>")
            for r, _t in bad:
                tail = " — tugagan" if r["status"] in ("out", "neg") else ""
                days = ", ~%s kunga yetadi" % num(r["days_left"]) if r["days_left"] is not None else ""
                lines.append("• %s: %s %s (minimal %s)%s%s" % (esc(r["name"]), num(r["qty"]), esc(r["uom"]),
                                                              num(r["min_qty"], 0), days, tail))
        if restored:
            if lines:
                lines.append("")
            lines.append("✅ <b>Qoldiq tiklandi</b>")
            for r, _t in restored:
                lines.append("• %s: %s %s" % (esc(r["name"]), num(r["qty"]), esc(r["uom"])))
        if self._send_contacts(contacts, "\n".join(lines), "alert"):
            for _r, tmpl in bad:
                tmpl.craf_tg_alert = True
            for _r, tmpl in restored:
                tmpl.craf_tg_alert = False

    # ================================================================== bot: kelgan xabarlar
    @api.model
    def _reply(self, chat_id, text):
        contact = self._contacts().filtered(lambda c: c.telegram_id.strip() == str(chat_id))[:1]
        return self.send(chat_id, text, kind="reply", contact=contact or None)

    @api.model
    def handle_message(self, chat_id, text, first_name=""):
        chat_id = str(chat_id)
        contacts = self._contacts().filtered(lambda c: c.telegram_id.strip() == chat_id)
        cmd = (text or "").strip().split()[0].lower().split("@")[0] if (text or "").strip() else ""
        if cmd in ("/start", "/id") or not contacts:
            if contacts:
                bolims = ", ".join(sorted(set(contacts.bolim_id.mapped("name"))))
                msg = ("Assalomu alaykum, %s!\nSiz Craf dasturida ro'yxatdasiz: <b>%s</b>.\n"
                       "Telegram ID: <code>%s</code>\n\n%s" % (esc(contacts[0].name), esc(bolims), chat_id, HELP))
            else:
                msg = ("Assalomu alaykum%s!\nSizning Telegram ID ingiz: <code>%s</code>\n\n"
                       "Shu raqamni Craf dasturida bo'lim mas'ullari ro'yxatiga yozdiring — shundan keyin "
                       "bot sizga hisobot va eslatmalar yuboradi." % (", " + esc(first_name) if first_name else "", chat_id))
            return self._reply(chat_id, msg)
        if cmd == "/qoldiq":
            return self._reply(chat_id, "🔥 <b>Liteyka</b> — %s\n%s" % (
                self._now().strftime("%d.%m.%Y %H:%M"), self._stock_text()))
        if cmd == "/hisobot":
            codes = sorted(set(contacts.bolim_id.mapped("code")))
            return self._reply(chat_id, "\n\n".join(self.report_text(c) for c in codes))
        return self._reply(chat_id, HELP)

    @api.model
    def poll(self):
        """Yangi xabarlarni Telegramdan oladi va javob beradi (cron, har daqiqa)."""
        if not self._token():
            return 0
        offset = int(self._param(P_OFFSET, "0") or 0)
        try:
            updates = self._api("getUpdates", {"offset": offset, "timeout": 0, "allowed_updates": ["message"]})
        except TelegramError as err:
            _logger.warning("Telegram getUpdates: %s", err)
            return 0
        for upd in updates or []:
            offset = max(offset, upd["update_id"] + 1)
            self._set_param(P_OFFSET, str(offset))
            msg = upd.get("message") or {}
            chat = msg.get("chat") or {}
            if chat.get("type") != "private" or not msg.get("text"):
                continue
            try:
                self.handle_message(chat["id"], msg["text"], (msg.get("from") or {}).get("first_name", ""))
            except Exception:  # noqa: BLE001 — bitta xabar xatosi botni to'xtatmasin
                _logger.exception("Telegram xabarini qayta ishlab bo'lmadi")
            self.env.cr.commit()  # javob yuborildi — qayta yuborilmasin
        return len(updates or [])

    # ================================================================== cron
    @api.model
    def _cron_poll(self):
        self.poll()

    @api.model
    def _cron_daily(self):
        """Har 15 daqiqada: belgilangan soat bo'ldi va bugun hali yuborilmagan bo'lsa — kunlik hisobot."""
        if not self._token():
            return
        now = self._now()
        hour = int(self._param(P_HOUR, "8") or 8)
        today = now.date().isoformat()
        if now.hour < hour or self._param(P_LAST_DAILY) == today:
            return
        self._set_param(P_LAST_DAILY, today)
        self.env.cr.commit()  # ikki marta yuborilmasin
        self.send_daily()

    # ================================================================== tugmalar uchun
    @api.model
    def check_bot(self):
        try:
            me = self._api("getMe")
        except TelegramError as err:
            raise UserError(str(err)) from err
        username = me.get("username") or ""
        self._set_param(P_BOT, username)
        return username
