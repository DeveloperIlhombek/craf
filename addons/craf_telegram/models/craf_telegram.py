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


_logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot%s/%s"
TZ = "Asia/Tashkent"
P_TOKEN = "craf_telegram.token"
P_BOT = "craf_telegram.bot_username"
P_OFFSET = "craf_telegram.update_offset"
P_HOUR = "craf_telegram.daily_hour"
P_LAST_DAILY = "craf_telegram.last_daily"
DEFAULT_HOUR = 11  # kunlik hisobot (kechagi kun) — Toshkent vaqti bilan 11:00
MAX_LEN = 4000
BOLIM_ICON = {"litey": "🔥", "press": "⚙️", "boyash": "🎨"}
HELP = ("Buyruqlar:\n/qoldiq — kam qolgan va tugagan materiallar\n/hisobot — kechagi hisobot\n/id — Telegram ID ingiz")


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
    # Xabar ixcham: bo'lim bo'yicha kechagi ish yakuni (bir-ikki qator) va faqat muammoli qoldiq —
    # tugagan, minimaldan kam va tez tugaydigan materiallar. Hammasi yetarli bo'lsa — bitta qator.
    TOP = 5

    @staticmethod
    def _days(value):
        return num(value, 0 if value >= 3 else 1)

    def _top(self, items):
        """[(qiymat, matn)] → eng kattalari, qolgani «+N ta»."""
        items = sorted(items, key=lambda x: -x[0])
        text = ", ".join(t for _v, t in items[:self.TOP])
        if len(items) > self.TOP:
            text += " +%s ta" % (len(items) - self.TOP)
        return text

    def _stock_rows(self, code):
        """Bo'lim prognozi qatorlari bir xil ko'rinishda: name, qty, uom, min_qty, days_left, status, tmpl_id."""
        if code == "litey":
            return self.env["craf.litey.hisobot"].sudo().with_context(tz=TZ)._forecast_rows()[3]
        if code == "press":
            rows = self.env["craf.extrusion.shift"].sudo()._craf_billet_forecast().values()
        else:
            rows = self.env["craf.paint.batch"].sudo()._craf_material_forecast().values()
        return [dict(r, name=r["product"].name, tmpl_id=r["product"].product_tmpl_id.id) for r in rows]

    def _alert_lines(self, rows):
        out = [r for r in rows if r["status"] in ("out", "neg")]
        low = [r for r in rows if r["status"] == "low"]
        soon = sorted([r for r in rows if r["status"] == "soon"], key=lambda r: r["days_left"] or 0)
        lines = []
        if out:
            lines.append("⛔ Tugagan: " + ", ".join(esc(r["name"]) for r in out))
        if low:
            lines.append("⚠️ Kam: " + "; ".join("%s %s %s (min %s)" % (
                esc(r["name"]), num(r["qty"]), esc(r["uom"]), num(r["min_qty"], 0)) for r in low))
        if soon:
            lines.append("⏳ Tez tugaydi: " + "; ".join("%s ~%s kun" % (esc(r["name"]), self._days(r["days_left"]))
                                                      for r in soon if r["days_left"] is not None))
        return lines

    def _stock_text(self, code="litey"):
        lines = self._alert_lines(self._stock_rows(code))
        return "\n".join(lines) if lines else "✅ Qoldiq yetarli"

    def _title(self, code, day):
        title = {"litey": "Liteyka", "press": "Press", "boyash": "Bo'yash va qadoqlash"}[code]
        return "%s <b>%s</b> · %s" % (BOLIM_ICON[code], title, day.strftime("%d.%m"))

    def _litey_text(self, day):
        H = self.env["craf.litey.hisobot"].sudo().with_context(tz=TZ)
        d = H.get_data(fields.Date.to_string(day), fields.Date.to_string(day))
        k = d["kpi"]
        lines = [self._title("litey", day)]
        if k["melts"]:
            lines.append("Plavka %s ta: stalba %s kg, ugar %s %%" % (k["melts"], num(k["billet"], 0),
                                                                   num(k["loss_pct"], 1)))
        if k["drafts"]:
            lines.append("Qoralama plavka: %s ta" % k["drafts"])
        # ombor harakatlari bo'yicha (plavka hujjati bo'lmasa ham — Excel / qo'lda yozilgan sarf va kirim)
        for title, key in (("Sarf", "spent"), ("Kirim", "kirim"), ("Chiqdi", "out")):
            items = []
            for r in d["movement"]:
                value = {"spent": r["sarf_plavka"] + r["sarf_boshqa"], "kirim": r["kirim"],
                         "out": r["chiqish_plavka"] + r["chiqish_boshqa"]}[key]
                if value > 1e-6:
                    items.append((value, "%s %s %s" % (esc(r["name"]), num(value), esc(r["uom"]))))
            if items:
                lines.append("%s: %s" % (title, self._top(items)))
        if len(lines) == 1:
            lines.append("Harakat yozilmagan.")
        lines.append(self._stock_text("litey"))
        return "\n".join(lines)

    def _press_text(self, day):
        Shift = self.env["craf.extrusion.shift"].sudo()
        done = Shift.search([("date", "=", day), ("state", "=", "done")])
        drafts = Shift.search_count([("state", "=", "draft"), ("date", "<=", day)])
        lines = [self._title("press", day)]
        if done:
            parts = ["%s smena" % len(done)]
            if "basket_count" in Shift._fields and sum(done.mapped("basket_count")):
                parts.append("%s korzinka" % num(sum(done.mapped("basket_count")), 0))
            parts.append("%s dona" % num(sum(done.mapped("output_pcs")), 0))
            net = sum(done.mapped("basket_net_kg")) if "basket_net_kg" in Shift._fields else 0.0
            parts.append("netto %s kg" % num(net or sum(done.mapped("output_kg")), 0))
            lines.append(" · ".join(parts))
            lines.append("Brak %s kg · pitak %s kg" % (num(sum(done.mapped("scrap_qty")), 0),
                                                       num(sum(done.mapped("rest_qty")), 0)))
            billet = sum(done.mapped("billet_qty"))
            if billet:
                lines.append("Quyma %s kg, chiqish %s %%" % (num(billet, 0),
                                                            num(sum(done.mapped("output_kg")) / billet * 100, 1)))
            low = done.filtered(lambda s: s.norm_status == "low")
            if low:
                lines.append("⚠️ Normadan past: %s" % ", ".join(esc(s.name) for s in low))
        else:
            lines.append("Smena yozilmagan.")
        if drafts:
            lines.append("Qoralama: %s ta" % drafts)
        lines.append(self._stock_text("press"))
        return "\n".join(lines)

    def _boyash_text(self, day):
        lines = [self._title("boyash", day)]
        drafts = 0
        chem = self.env["craf.chem.treatment"].sudo()
        done = chem.search([("date", "=", day), ("state", "=", "done")])
        drafts += chem.search_count([("state", "=", "draft"), ("date", "<=", day)])
        if done:
            lines.append("Kimyo: %s korzinka, %s kg profil, kimyo %s kg" % (
                num(sum(done.mapped("basket_count")), 0), num(sum(done.mapped("kg_total")), 0),
                num(sum(done.mapped("chem_kg")))))
        if "craf.paint.sort" in self.env:
            sort = self.env["craf.paint.sort"].sudo()
            done = sort.search([("date", "=", day), ("state", "=", "done")])
            drafts += sort.search_count([("state", "=", "draft"), ("date", "<=", day)])
            if done:
                brak, cut = sum(done.mapped("brak_pcs")), sum(done.mapped("cut_pcs"))
                parts = (["brak %s dona" % num(brak, 0)] if brak else []) + (
                    ["6→5 m %s dona" % num(cut, 0)] if cut else [])
                lines.append("Ajratildi: %s → Liteykaga %s kg" % (", ".join(parts), num(sum(done.mapped("kg_total")))))
        paint = self.env["craf.paint.batch"].sudo()
        done = paint.search([("date", "=", day), ("state", "=", "done")])
        drafts += paint.search_count([("state", "=", "draft"), ("date", "<=", day)])
        if done:
            pcs_in = sum(done.mapped("pcs_in"))
            defect = sum(done.mapped("pcs_defect"))
            lines.append("Bo'yaldi: %s dona (%s kg), brak %s %%, kukun %s kg" % (
                num(sum(done.mapped("pcs_ok")), 0), num(sum(done.mapped("kg_ok")), 0),
                num(defect / pcs_in * 100 if pcs_in else 0, 1), num(sum(done.mapped("powder_qty")))))
            low = done.filtered(lambda b: b.norm_status == "low")
            if low:
                lines.append("⚠️ Normadan tashqari: %s" % ", ".join(esc(b.name) for b in low))
        if len(lines) == 1:
            lines.append("Hujjat yozilmagan.")
        if drafts:
            lines.append("Qoralama: %s ta" % drafts)
        lines.append(self._stock_text("boyash"))
        return "\n".join(lines)

    @api.model
    def report_text(self, code, day=None):
        day = day or self._yesterday()
        return {"litey": self._litey_text, "press": self._press_text, "boyash": self._boyash_text}[code](day)

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
    def _min_qty_alerts(self, rows, code="litey"):
        """Material minimaldan kamaysa yoki tugasa — bir marta; tiklansa — bir marta. Faqat o'zgarganlari."""
        if not self._token():
            return
        contacts = self._contacts(code, "notify_min_qty")
        Tmpl = self.env["product.template"].sudo()
        bad, restored = [], []
        for r in rows:
            if not r["min_qty"]:
                continue
            tmpl = Tmpl.browse(r.get("tmpl_id") or r["product"].product_tmpl_id.id)
            name = r.get("name") or tmpl.name
            is_bad = r["status"] in ("low", "out", "neg")
            if is_bad and not tmpl.craf_tg_alert:
                bad.append((r, tmpl, name))
            elif not is_bad and tmpl.craf_tg_alert:
                restored.append((r, tmpl, name))
        if not contacts or not (bad or restored):
            return
        title = {"litey": "Liteyka", "press": "Press", "boyash": "Bo'yash va qadoqlash"}[code]
        lines = ["%s <b>%s</b>" % (BOLIM_ICON[code], title)]
        for r, _t, name in bad:
            state = "⛔ tugadi" if r["status"] in ("out", "neg") else "⚠️ kam"
            days = ", ~%s kun" % self._days(r["days_left"]) if r["days_left"] is not None else ""
            lines.append("%s: %s — %s %s (min %s)%s" % (state, esc(name), num(r["qty"]), esc(r["uom"]),
                                                       num(r["min_qty"], 0), days))
        for r, _t, name in restored:
            lines.append("✅ tiklandi: %s — %s %s" % (esc(name), num(r["qty"]), esc(r["uom"])))
        if self._send_contacts(contacts, "\n".join(lines), "alert"):
            for _r, tmpl, _n in bad:
                tmpl.craf_tg_alert = True
            for _r, tmpl, _n in restored:
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
            codes = [c for c in ("litey", "press", "boyash") if c in contacts.bolim_id.mapped("code")]
            return self._reply(chat_id, "\n\n".join(
                "%s\n%s" % (self._title(c, self._now().date()), self._stock_text(c)) for c in codes))
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
        hour = int(self._param(P_HOUR, DEFAULT_HOUR) or DEFAULT_HOUR)
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
