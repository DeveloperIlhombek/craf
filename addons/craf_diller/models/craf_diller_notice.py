import logging

from odoo import api, fields, models

from odoo.addons.craf_telegram.models.craf_telegram import TelegramError, esc

from .sale_order import money

_logger = logging.getLogger(__name__)
BATCH = 30


class CrafDillerNotice(models.Model):
    _name = "craf.diller.notice"
    _description = "Dillerga xabar"
    _order = "id desc"

    partner_id = fields.Many2one("res.partner", "Diller", required=True, index=True, ondelete="cascade")
    order_id = fields.Many2one("sale.order", "Buyurtma", ondelete="set null")
    title = fields.Char("Sarlavha", required=True)
    body = fields.Char("Matn")
    attachment_ids = fields.Many2many("ir.attachment", string="Rasmlar")
    tg_state = fields.Selection([("none", "Yuborilmaydi"), ("pending", "Navbatda"), ("sent", "Yuborildi"),
                                 ("error", "Xato")], default="none", index=True)

    @api.model
    def _craf_chats(self, dealer):
        """Dillerning Telegram ulangan logini."""
        return self.env["res.partner"].sudo().search(
            [("id", "child_of", dealer.id), ("craf_telegram_id", "!=", False)])

    @api.model
    def _craf_push(self, dealer, title, body, order=None, photos=None):
        """Bildirishnoma yoziladi; Telegram alohida (cron) yuboriladi — yuklovchini kuttirmaydi."""
        return self.sudo().create({
            "partner_id": dealer.id, "title": title, "body": body, "order_id": order.id if order else False,
            "attachment_ids": [(6, 0, photos.ids)] if photos else False,
            "tg_state": "pending" if self._craf_chats(dealer) else "none",
        })

    @api.model
    def _cron_send(self):
        TG = self.env["craf.telegram"].sudo()
        if not TG._token():
            return
        for notice in self.sudo().search([("tg_state", "=", "pending")], order="id", limit=BATCH):
            text = "<b>%s</b>\n%s" % (esc(notice.title), esc(notice.body))
            state = "sent"
            for person in self._craf_chats(notice.partner_id):
                chat = person.craf_telegram_id.strip()
                if not TG.send(chat, text, kind="info"):
                    state = "error"
                    continue
                for photo in notice.attachment_ids:
                    try:
                        TG.send_photo(chat, photo, notice.title)
                    except TelegramError as err:
                        _logger.warning("Diller rasmi yuborilmadi: %s", err)
            notice.tg_state = state
            self.env.cr.commit()  # yuborildi — qayta yuborilmasin

    def _active_dealers(self):
        return self.env["res.partner"].sudo().search([("craf_is_diller", "=", True),
                                                      ("craf_diller_blocked", "=", False)])

    @api.model
    def _cron_debt(self):
        """Haftalik qarz eslatmasi."""
        symbol = self.env.company.currency_id.symbol or ""
        dealers = self._active_dealers()
        debts = self.env["craf.sotuv"].sudo()._craf_debt(set(dealers.ids))
        for dealer in dealers:
            debt = debts.get(dealer.id, 0.0)
            if debt > 0.5:
                self._craf_push(dealer, "Qarz eslatmasi", "Joriy qarzingiz: %s %s." % (money(debt), symbol))

    @api.model
    def _cron_news(self):
        """Kunlik: yangi mahsulot va o'zgargan narxlar haqida bitta xabar."""
        Param = self.env["ir.config_parameter"].sudo()
        key = "craf_diller.news_last"
        now = fields.Datetime.now()
        last = fields.Datetime.to_datetime(Param.get_param(key) or fields.Datetime.to_string(now))
        Param.set_param(key, fields.Datetime.to_string(now))
        domain = self.env["craf.sotuv"].sudo()._finished_domain()
        Product = self.env["product.product"].sudo()
        fresh = Product.search_count(domain + [("create_date", ">=", last)])
        prices = Product.search(domain + [("product_tmpl_id.craf_price_date", ">=", last)]).product_tmpl_id
        parts = []
        if fresh:
            parts.append("%s ta yangi mahsulot" % fresh)
        if prices:
            parts.append("%s ta mahsulot narxi o'zgardi" % len(prices))
        if parts:
            for dealer in self._active_dealers():
                self._craf_push(dealer, "Katalog yangilandi", ", ".join(parts) + ".")
